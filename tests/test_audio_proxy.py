"""Speech inputs and real HTTP dispatch, with native inference isolated."""

import base64
import io
import json
import sys
import threading
import types
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from subllm import audio
from subllm.proxy import SubLLMProxyHandler


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(16000)
        clip.writeframes(b"\0\0" * 1600)
    return output.getvalue()


@pytest.fixture
def assets(tmp_path, monkeypatch):
    model = tmp_path / "models" / "small"
    model.mkdir(parents=True)
    (model / "model.bin").write_bytes(b"test-model")
    voice = tmp_path / "models" / "test.onnx"
    voice.write_bytes(b"test-model")
    Path(str(voice) + ".json").write_text("{}")
    binary = tmp_path / "piper"
    binary.write_text("test executable fixture")
    binary.chmod(0o700)
    monkeypatch.setenv("SUBLLM_SPEECH_MODEL_ROOTS", str(model.parent))
    monkeypatch.setenv("SUBLLM_PIPER_BIN", str(binary))
    monkeypatch.setattr(audio, "_WHISPER_MODEL", None)
    monkeypatch.setattr(audio, "_WHISPER_KEY", None)
    return model, voice


def test_whisper_receives_parameters_without_download_and_reuses_model(assets, monkeypatch):
    model, _voice = assets
    loads, requests = [], []

    class Whisper:
        def __init__(self, path, **options):
            loads.append((path, options))

        def transcribe(self, clip, language=None, beam_size=5, vad_filter=False):
            requests.append((clip.read(), language, beam_size, vad_filter))
            return iter([types.SimpleNamespace(text=" rozpoznano ")]), types.SimpleNamespace(language="pl")

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Whisper))
    body = {
        "model": str(model),
        "audio_base64": base64.b64encode(wav_bytes()).decode(),
        "device": "cpu",
        "compute_type": "int8",
        "language": "pl-PL",
        "beam_size": 7,
        "vad_filter": True,
    }
    assert audio.transcribe(body)["text"] == "rozpoznano"
    assert audio.transcribe({**body, "beam_size": 2})["ok"] is True
    assert len(loads) == 1
    assert loads[0][1]["local_files_only"] is True
    assert requests[0][1:] == ("pl", 7, True)
    assert requests[1][2] == 2


def test_native_synthesis_preserves_voice_parameters_and_returns_wav(assets, monkeypatch):
    _model, voice = assets
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        Path(args[args.index("--output_file") + 1]).write_bytes(wav_bytes())
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(audio.subprocess, "run", run)
    result = audio.synthesize({"model": str(voice), "text": "Próba", "speed": 2, "noise_scale": 0.5})
    assert result["ok"] is True and base64.b64decode(result["audio_base64"]) == wav_bytes()
    assert calls[0][0][calls[0][0].index("--length_scale") + 1] == "0.5"
    assert calls[0][0][calls[0][0].index("--noise_scale") + 1] == "0.5"
    assert calls[0][1]["input"] == "Próba"


def test_invalid_audio_never_loads_a_model(assets, monkeypatch):
    model, _voice = assets
    with pytest.raises(audio.SpeechError) as error:
        audio.transcribe({"model": str(model), "audio_base64": "not base64"})
    assert error.value.code == "SPEECH_AUDIO_INVALID"


@pytest.fixture
def compressed_decoder(monkeypatch):
    observed = {"frames": [], "consumed": 0, "closed": False, "streams": 1}

    class Clip:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            observed["closed"] = True

        @property
        def streams(self):
            return types.SimpleNamespace(audio=[object()] * observed["streams"])

        def decode(self, **kwargs):
            for frame in observed["frames"]:
                observed["consumed"] += 1
                if isinstance(frame, Exception):
                    raise frame
                yield frame

    def open_clip(source, **kwargs):
        observed["raw"] = source.read()
        observed["format"] = kwargs["format"]
        return Clip()

    monkeypatch.setitem(sys.modules, "av", types.SimpleNamespace(open=open_clip))
    return observed


def audio_frame(samples=48000, rate=48000, channels=1):
    return types.SimpleNamespace(
        samples=samples, sample_rate=rate, layout=types.SimpleNamespace(channels=[0] * channels)
    )


@pytest.mark.parametrize(
    "signature,media,container", [(b"OggS", "audio/ogg", "ogg"), (b"\x1aE\xdf\xa3", "audio/webm", "matroska")]
)
@pytest.mark.parametrize("declared", [False, True])
def test_browser_container_without_type_or_with_codec_parameter_is_decoded(
    compressed_decoder, signature, media, container, declared
):
    raw = signature + b"\0" * 64
    compressed_decoder["frames"] = [audio_frame()]
    payload = {"audio_base64": base64.b64encode(raw).decode()}
    if declared:
        payload["media_type"] = media + ";codecs=opus"
    assert audio._audio(payload) == (raw, media)
    assert compressed_decoder["format"] == container
    assert compressed_decoder["closed"] is True


def test_compressed_duration_stops_decoding_before_model_inference(assets, monkeypatch, compressed_decoder):
    model, _ = assets
    compressed_decoder["frames"] = [
        audio_frame(48000 * 60),
        audio_frame(48000 * 60),
        audio_frame(),
        RuntimeError("must not consume"),
    ]
    monkeypatch.setattr(audio, "_model_path", lambda *_: pytest.fail("invalid audio reached the model"))
    with pytest.raises(audio.SpeechError) as error:
        audio.transcribe({"model": str(model), "audio_base64": base64.b64encode(b"OggS" + b"\0" * 64).decode()})
    assert error.value.code == "SPEECH_AUDIO_INVALID"
    assert compressed_decoder["consumed"] == 3
    assert compressed_decoder["closed"] is True


@pytest.mark.parametrize(
    "frames,streams",
    [
        ([], 1),
        ([audio_frame()], 0),
        ([audio_frame()], 2),
        ([audio_frame(rate=0)], 1),
        ([audio_frame(rate=384000)], 1),
        ([audio_frame(channels=6)], 1),
        ([audio_frame(samples=0)], 1),
        ([ValueError("corrupt stream")], 1),
    ],
)
def test_invalid_compressed_audio_never_reaches_remote_inference(monkeypatch, compressed_decoder, frames, streams):
    compressed_decoder.update(frames=frames, streams=streams)
    monkeypatch.setattr(audio, "_remote_transcribe", lambda *_: pytest.fail("invalid audio reached a provider"))
    with pytest.raises(audio.SpeechError) as error:
        audio.transcribe(
            {
                "model": "test",
                "engine": "openai",
                "media_type": "audio/ogg",
                "audio_base64": base64.b64encode(b"OggS" + b"\0" * 64).decode(),
            }
        )
    assert error.value.code == "SPEECH_AUDIO_INVALID"
    assert compressed_decoder["closed"] is True


@pytest.mark.parametrize("media", ["audio/wav", "audio/webm", "application/octet-stream", None, 42])
def test_explicit_media_type_must_match_the_audio_container(media, compressed_decoder):
    with pytest.raises(audio.SpeechError) as error:
        audio._audio({"audio_base64": base64.b64encode(b"OggS" + b"\0" * 64).decode(), "media_type": media})
    assert error.value.code == "SPEECH_AUDIO_INVALID"
    assert compressed_decoder["consumed"] == 0


def test_unavailable_compressed_decoder_fails_without_inference(monkeypatch):
    monkeypatch.setitem(sys.modules, "av", None)
    with pytest.raises(audio.SpeechError) as error:
        audio._audio({"audio_base64": base64.b64encode(b"OggS" + b"\0" * 64).decode()})
    assert error.value.code == "SPEECH_BACKEND_UNAVAILABLE"


def test_exact_duration_boundary_does_not_depend_on_float_rounding(compressed_decoder):
    compressed_decoder["frames"] = [audio_frame(samples=441, rate=44100)] * 12000
    raw = b"OggS" + b"\0" * 64
    assert audio._audio({"audio_base64": base64.b64encode(raw).decode()}) == (raw, "audio/ogg")
    assert compressed_decoder["consumed"] == 12000


@pytest.mark.parametrize(
    "signature,media,extension", [(b"OggS", "audio/ogg", "ogg"), (b"\x1aE\xdf\xa3", "audio/webm", "webm")]
)
def test_remote_transcription_preserves_the_validated_browser_format(
    monkeypatch, compressed_decoder, signature, media, extension
):
    compressed_decoder["frames"] = [audio_frame()]
    raw = signature + b"\0" * 64
    requests = []
    monkeypatch.setattr(audio, "_remote_request", lambda *args: requests.append(args) or b'{"text":"result"}')
    result = audio.transcribe({"engine": "openai", "model": "test", "audio_base64": base64.b64encode(raw).decode()})
    assert result["text"] == "result"
    assert f'filename="speech.{extension}"'.encode() in requests[0][1]
    assert f"Content-Type: {media}".encode() in requests[0][1]
    assert raw in requests[0][1]
    assert audio._WHISPER_MODEL is None


def test_model_outside_allowed_roots_is_rejected(assets, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "model.bin").write_bytes(b"test")
    with pytest.raises(audio.SpeechError) as error:
        audio.transcribe({"model": str(outside), "audio_base64": base64.b64encode(wav_bytes()).decode()})
    assert error.value.code == "SPEECH_MODEL_UNAVAILABLE"


def test_timeout_or_bad_native_output_is_not_reported_as_audio(assets, monkeypatch):
    _model, voice = assets

    def bad_output(args, **_kwargs):
        Path(args[args.index("--output_file") + 1]).write_bytes(b"not audio" * 20)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(audio.subprocess, "run", bad_output)
    with pytest.raises(audio.SpeechError) as error:
        audio.synthesize({"model": str(voice), "text": "test"})
    assert error.value.code == "SPEECH_RESPONSE_INVALID"


@pytest.fixture
def http_proxy():
    server = ThreadingHTTPServer(("127.0.0.1", 0), SubLLMProxyHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def post(base, payload, path="/v1/speech/transcribe"):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.loads(error.read())


def test_proxy_dispatches_speech_without_chat_or_provider_fallback(http_proxy, monkeypatch):
    seen = []
    monkeypatch.setattr(audio, "transcribe", lambda payload: seen.append(payload) or {"ok": True, "text": "result"})
    status, result = post(http_proxy, {"model": "test", "audio_base64": "example"})
    assert status == 200 and result["text"] == "result"
    assert seen == [{"model": "test", "audio_base64": "example"}]


def test_proxy_preserves_explicit_backend_unavailability(http_proxy, monkeypatch):
    def unavailable(_payload):
        raise audio.SpeechError("SPEECH_BACKEND_UNAVAILABLE", "backend unavailable", 503)

    monkeypatch.setattr(audio, "transcribe", unavailable)
    status, result = post(http_proxy, {"model": "test", "audio_base64": "example"})
    assert status == 503
    assert result["error"]["code"] == "SPEECH_BACKEND_UNAVAILABLE"
    assert "text" not in result


def test_policy_chat_receives_native_sampling_controls_and_rejects_ignored_options(http_proxy, monkeypatch):
    from subllm.client_types import CompletionResponse
    from subllm.runtime_profile import _REQUEST_PARAMETERS

    seen = []
    monkeypatch.setattr("subllm.proxy.is_upstream_ollama_alive", lambda *_args, **_kwargs: False)

    def execute(*_args, **_kwargs):
        seen.append(dict(_REQUEST_PARAMETERS.get()))
        return CompletionResponse("test", "test", "test")

    monkeypatch.setattr(SubLLMProxyHandler, "_execute_model_or_route", execute)
    payload = {
        "model": "qwen2.5",
        "stream": False,
        "messages": [{"role": "user", "content": "test"}],
        "options": {"temperature": 0.3, "num_predict": 21},
    }
    assert post(http_proxy, payload, "/api/chat")[0] == 200
    assert seen == [{"temperature": 0.3, "max_tokens": 21}]
    payload["options"]["num_ctx"] = 4096
    assert post(http_proxy, payload, "/api/chat")[0] == 400
    assert len(seen) == 1


def test_native_ollama_request_keeps_context_and_sampling_options(http_proxy, monkeypatch):
    seen = []
    probes = []
    monkeypatch.setattr("subllm.proxy.adaptive.policy", lambda: None)

    def alive(*_args, **_kwargs):
        probes.append(True)
        assert len(probes) == 1, "Native route must use the observed liveness result once"
        return True

    monkeypatch.setattr("subllm.proxy.is_upstream_ollama_alive", alive)

    def forward(handler, method, path, payload):
        seen.append((method, path, payload))
        handler._json(200, {"message": {"content": "test"}})

    monkeypatch.setattr(SubLLMProxyHandler, "_forward_upstream", forward)
    payload = {
        "model": "test-native-unregistered",
        "stream": False,
        "messages": [{"role": "user", "content": "test"}],
        "options": {"num_ctx": 4096, "top_k": 20},
    }
    assert post(http_proxy, payload, "/api/chat")[0] == 200
    assert seen == [("POST", "/api/chat", payload)]
