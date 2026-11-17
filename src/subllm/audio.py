"""Speech inference adapters behind the SubLLM gateway, never in UI clients."""

from __future__ import annotations

import base64
import importlib.util
import inspect
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
import wave
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .runtime_profile import PARAMETERS, ProfileError, capabilities, validate_parameters

MAX_AUDIO_BYTES = 7 * 1024 * 1024
_MODEL_LOCK = threading.RLock()
_WHISPER_MODEL = None
_WHISPER_KEY = None


class SpeechError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


def _roots():
    configured = os.environ.get("SUBLLM_SPEECH_MODEL_ROOTS")
    if configured:
        return [Path(value).expanduser().resolve() for value in configured.split(os.pathsep) if value]
    return [
        Path("/usr/share/heyasa-speech"),
        Path("/usr/share/piper"),
        Path.home() / ".config/stts-python/models/piper",
        Path.home() / ".local/share/heyasa/models",
    ]


def _piper_bin():
    explicit = os.environ.get("SUBLLM_PIPER_BIN")
    candidates = (
        [explicit] if explicit else [shutil.which("piper"), str(Path.home() / ".config/stts-python/bin/piper/piper")]
    )
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), None)


def _model_path(model, role):
    if not isinstance(model, str) or not model or len(model) > 2048 or "\x00" in model:
        raise SpeechError("SPEECH_MODEL_INVALID", "A model identifier is required")
    if model == "piper:default":
        model = (
            os.environ.get("SUBLLM_PIPER_MODEL")
            or os.environ.get("HEYASA_PIPER_MODEL")
            or os.environ.get("WILLMUX_PIPER_MODEL")
            or ""
        )
        if not model:
            models = _installed_models()
            model = next((m["id"] for m in models if m["role"] == "tts"), "")
    candidates = [Path(model).expanduser()] if Path(model).is_absolute() else []
    for root in _roots():
        candidates.extend((root / model, root / ("faster-whisper-" + model)))
    for candidate in candidates:
        path = candidate.resolve()
        if not any(path.is_relative_to(root.resolve()) for root in _roots()):
            continue
        if role == "stt" and path.is_dir() and (path / "model.bin").is_file():
            return path
        if role == "tts" and path.is_file() and path.suffix == ".onnx" and Path(str(path) + ".json").is_file():
            return path
    raise SpeechError(
        "SPEECH_MODEL_UNAVAILABLE", "Configured speech model is not installed in an allowed model root", 503
    )


def _installed_models():
    result = []
    for root in _roots():
        if not root.is_dir():
            continue
        # Bound discovery to the declared model roots, without downloading.
        for path in root.rglob("model.bin"):
            if len(result) >= 100:
                break
            result.append({"id": str(path.parent), "role": "stt", "engine": "faster-whisper"})
        for path in root.rglob("*.onnx"):
            if len(result) >= 100:
                break
            if Path(str(path) + ".json").is_file():
                result.append({"id": str(path), "role": "tts", "engine": "piper"})
    return result


def speech_capabilities():
    result = capabilities()
    result["models"] = _installed_models()
    result["backends"] = {
        "faster-whisper": importlib.util.find_spec("faster_whisper") is not None,
        "piper": _piper_bin() is not None,
        "stt-openai": bool(os.environ.get("SUBLLM_STT_URL")),
        "tts-openai": bool(os.environ.get("SUBLLM_TTS_URL")),
    }
    return result


def _parameters(payload, role, input_name):
    if not isinstance(payload, dict):
        raise SpeechError("SPEECH_REQUEST_INVALID", "A JSON object is required")
    allowed = set(PARAMETERS[role]) | {"model", input_name, "media_type"}
    if set(payload) - allowed:
        raise SpeechError("SPEECH_PARAMETER_INVALID", "Unsupported speech request fields")
    model = payload.get("model")
    if not isinstance(model, str) or not model or len(model) > 2048 or any(ord(c) < 32 for c in model):
        raise SpeechError("SPEECH_MODEL_INVALID", "A model identifier is required")
    try:
        return validate_parameters(role, {k: v for k, v in payload.items() if k in PARAMETERS[role]})
    except ProfileError as error:
        raise SpeechError("SPEECH_PARAMETER_INVALID", str(error)) from None


def _audio(payload):
    encoded = payload.get("audio_base64")
    if not isinstance(encoded, str) or len(encoded) > (MAX_AUDIO_BYTES * 4 // 3 + 8):
        raise SpeechError("SPEECH_AUDIO_INVALID", "A bounded base64 audio clip is required", 413)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise SpeechError("SPEECH_AUDIO_INVALID", "Invalid audio encoding") from None
    if not 44 <= len(raw) <= MAX_AUDIO_BYTES:
        raise SpeechError("SPEECH_AUDIO_INVALID", "Audio size is outside supported bounds", 413)
    media_type = payload.get("media_type", "audio/wav")
    if media_type not in {"audio/wav", "audio/x-wav", "audio/webm", "audio/ogg"}:
        raise SpeechError("SPEECH_AUDIO_INVALID", "Unsupported audio media type", 415)
    if media_type in {"audio/wav", "audio/x-wav"}:
        try:
            with wave.open(io.BytesIO(raw)) as clip:
                if (
                    not 0 < clip.getframerate() <= 192000
                    or clip.getnchannels() not in {1, 2}
                    or clip.getnframes() / clip.getframerate() > 120
                ):
                    raise ValueError
        except (wave.Error, EOFError, ValueError):
            raise SpeechError("SPEECH_AUDIO_INVALID", "Invalid or excessive PCM WAV duration") from None
    return raw, media_type


def transcribe(payload):
    options = _parameters(payload, "stt", "audio_base64")
    raw, media_type = _audio(payload)
    engine = options.pop("engine", "faster-whisper")
    timeout = options.pop("timeout", 120)
    if engine == "openai":
        return _remote_transcribe(payload.get("model"), raw, media_type, options, timeout)
    path = _model_path(payload.get("model"), "stt")
    device = options.pop("device", "auto")
    compute = options.pop("compute_type", "int8")
    threads = options.pop("cpu_threads", min(8, os.cpu_count() or 1))
    extra = options.pop("backend_options", {})
    if set(extra) & set(PARAMETERS["stt"]):
        raise SpeechError("SPEECH_PARAMETER_INVALID", "Use named controls for declared STT parameters")
    options.update(extra)
    if options.get("language"):
        options["language"] = options["language"].split("-")[0].split("_")[0]
    elif "language" in options:
        options["language"] = None
    global _WHISPER_MODEL, _WHISPER_KEY
    try:
        from faster_whisper import WhisperModel

        with _MODEL_LOCK:
            key = (str(path), device, compute, threads)
            if key != _WHISPER_KEY:
                model = WhisperModel(
                    str(path), device=device, compute_type=compute, cpu_threads=threads, local_files_only=True
                )
                _WHISPER_MODEL, _WHISPER_KEY = model, key
            inspect.signature(_WHISPER_MODEL.transcribe).bind(io.BytesIO(raw), **options)
            segments, info = _WHISPER_MODEL.transcribe(io.BytesIO(raw), **options)
            text = " ".join(segment.text.strip() for segment in segments).strip()
    except (TypeError, ValueError):
        raise SpeechError("SPEECH_PARAMETER_INVALID", "The speech backend rejected model parameters") from None
    except Exception:
        raise SpeechError(
            "SPEECH_BACKEND_UNAVAILABLE", "Local speech recognition could not be completed", 503
        ) from None
    return {
        "schema": "subllm.speech-transcription/v1",
        "ok": True,
        "text": text,
        "engine": "faster-whisper",
        "model": payload["model"],
        "language": info.language,
    }


def synthesize(payload):
    options = _parameters(payload, "tts", "text")
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 4096:
        raise SpeechError("SPEECH_TEXT_INVALID", "Speech text must contain 1 to 4096 characters")
    engine = options.pop("engine", "piper")
    timeout = options.pop("timeout", 120)
    if engine == "openai":
        return _remote_synthesize(payload.get("model"), text, options, timeout)
    path = _model_path(payload.get("model"), "tts")
    binary = _piper_bin()
    if not binary:
        raise SpeechError("SPEECH_BACKEND_UNAVAILABLE", "Native Piper is not installed", 503)
    if options.pop("voice", ""):
        raise SpeechError("SPEECH_PARAMETER_INVALID", "Select the Piper voice with the model control")
    options.pop("language", None)
    options.pop("format", None)
    if "speed" in options:
        if "length_scale" in options:
            raise SpeechError("SPEECH_PARAMETER_INVALID", "Choose speed or length_scale")
        options["length_scale"] = 1 / options.pop("speed")
    args = [binary, "--model", str(path)]
    for name, value in options.items():
        args.extend(["--" + name, str(value)])
    environment = dict(os.environ)
    environment["LD_LIBRARY_PATH"] = str(Path(binary).parent) + os.pathsep + environment.get("LD_LIBRARY_PATH", "")
    try:
        with tempfile.TemporaryDirectory(prefix="subllm-tts-") as directory:
            output = Path(directory) / "speech.wav"
            result = subprocess.run(
                [*args, "--output_file", str(output)],
                input=text,
                text=True,
                capture_output=True,
                timeout=timeout,
                env=environment,
                check=False,
            )
            if result.returncode or not output.is_file() or not 44 < output.stat().st_size <= MAX_AUDIO_BYTES:
                raise SpeechError("SPEECH_BACKEND_UNAVAILABLE", "Piper did not produce a supported audio clip", 503)
            raw = output.read_bytes()
            try:
                with wave.open(io.BytesIO(raw)) as clip:
                    if not clip.getnframes():
                        raise ValueError
            except (wave.Error, EOFError, ValueError):
                raise SpeechError("SPEECH_RESPONSE_INVALID", "Piper did not return PCM WAV", 502) from None
    except (OSError, subprocess.TimeoutExpired):
        raise SpeechError("SPEECH_BACKEND_UNAVAILABLE", "Local speech synthesis could not be completed", 503) from None
    return {
        "schema": "subllm.speech-synthesis/v1",
        "ok": True,
        "engine": "piper",
        "model": payload["model"],
        "media_type": "audio/wav",
        "audio_base64": base64.b64encode(raw).decode(),
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args):
        raise URLError("Speech provider redirects are forbidden")


def _remote_request(role, data, content_type, timeout):
    url = os.environ.get("SUBLLM_" + role.upper() + "_URL")
    if not url:
        raise SpeechError("SPEECH_BACKEND_UNAVAILABLE", "Remote speech provider is not configured", 503)
    headers = {"Content-Type": content_type}
    key = os.environ.get("SUBLLM_" + role.upper() + "_API_KEY", "")
    if key:
        headers["Authorization"] = "Bearer " + key
    request = Request(url, data=data, headers=headers, method="POST")
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(MAX_AUDIO_BYTES + 1)
    except (HTTPError, URLError, OSError, TimeoutError):
        raise SpeechError("SPEECH_BACKEND_UNAVAILABLE", "Remote speech inference could not be confirmed", 503) from None
    if len(raw) > MAX_AUDIO_BYTES:
        raise SpeechError("SPEECH_RESPONSE_INVALID", "Remote speech response exceeds the size limit", 502)
    return raw


def _remote_transcribe(model, audio, media_type, options, timeout):
    if set(options) - {"language", "temperature", "initial_prompt"}:
        raise SpeechError("SPEECH_PARAMETER_INVALID", "Unsupported remote STT parameters")
    boundary = "subllm-" + uuid.uuid4().hex
    fields = {"model": model, **options}
    if "initial_prompt" in fields:
        fields["prompt"] = fields.pop("initial_prompt")
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
         f'Content-Type: {media_type}\r\n\r\n').encode()
        + audio
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    raw = _remote_request("stt", b"".join(parts), "multipart/form-data; boundary=" + boundary, timeout)
    try:
        result = json.loads(raw)
        if not isinstance(result.get("text"), str):
            raise ValueError
    except (ValueError, AttributeError):
        raise SpeechError("SPEECH_RESPONSE_INVALID", "Remote STT returned invalid text", 502) from None
    return {
        "schema": "subllm.speech-transcription/v1",
        "ok": True,
        "text": result["text"],
        "engine": "openai",
        "model": model,
    }


def _remote_synthesize(model, text, options, timeout):
    if set(options) - {"voice", "speed", "format", "language"}:
        raise SpeechError("SPEECH_PARAMETER_INVALID", "Unsupported remote TTS parameters")
    options.pop("language", None)
    options.pop("format", None)
    body = {"model": model, "input": text, "response_format": "wav", **options}
    raw = _remote_request("tts", json.dumps(body).encode(), "application/json", timeout)
    try:
        with wave.open(io.BytesIO(raw)) as clip:
            if not clip.getnframes():
                raise ValueError
    except (wave.Error, EOFError, ValueError):
        raise SpeechError("SPEECH_RESPONSE_INVALID", "Remote TTS did not return PCM WAV", 502) from None
    return {
        "schema": "subllm.speech-synthesis/v1",
        "ok": True,
        "engine": "openai",
        "model": model,
        "media_type": "audio/wav",
        "audio_base64": base64.b64encode(raw).decode(),
    }
