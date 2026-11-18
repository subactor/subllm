import base64
import io
import sys
import wave
from types import SimpleNamespace

import pytest

from subllm import audio
from subllm.runtime_profile import default_profile, validate_profile


@pytest.fixture
def model(tmp_path, monkeypatch):
    root = tmp_path / "models"
    path = root / "polish"
    for name in ("am/final.mdl", "conf/mfcc.conf"):
        marker = path / name
        marker.parent.mkdir(parents=True)
        marker.touch()
    monkeypatch.setenv("SUBLLM_SPEECH_MODEL_ROOTS", str(root))
    monkeypatch.setattr(audio, "_VOSK_PATH", None)
    monkeypatch.setattr(audio, "_VOSK_MODEL", None)
    return path


def clip():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setparams((2, 2, 44100, 0, "NONE", ""))
        wav.writeframes(bytes(4410 * 4))
    return buf.getvalue()


def test_discovery_and_profile(model):
    entry = {"id": str(model), "role": "stt", "engine": "vosk"}
    assert entry in audio.speech_capabilities()["models"]
    profile = default_profile()
    profile["roles"]["stt"] = {"model": entry["id"], "parameters": {"engine": "vosk"}}
    assert validate_profile(profile)["roles"]["stt"] == profile["roles"]["stt"]
    assert audio._model_path("polish", "vosk") == model
    with pytest.raises(audio.SpeechError, match="not installed"):
        audio._model_path("polish", "stt")


def test_incomplete_or_outside_model_rejected(model, tmp_path):
    marker = model / "am/final.mdl"
    marker.unlink()
    external = tmp_path / "outside.mdl"
    external.touch()
    marker.symlink_to(external)
    assert not audio.speech_capabilities()["models"]
    with pytest.raises(audio.SpeechError, match="not installed"):
        audio._model_path(str(model), "vosk")


def test_model_is_reused_and_segments_belong_to_each_request(model, monkeypatch):
    loads, sessions = [], []

    class Recognizer:
        def __init__(self, instance, rate):
            assert instance is model and rate == 16000
            self.chunks = []
            sessions.append(self)

        def AcceptWaveform(self, pcm):
            self.chunks.append(pcm)
            return len(self.chunks) == 1

        def Result(self):
            return '{"text":"pierwsza"}'

        def FinalResult(self):
            return '{"text":"druga"}'

    def load(path):
        loads.append(path)
        return model

    monkeypatch.setitem(sys.modules, "vosk", SimpleNamespace(Model=load, KaldiRecognizer=Recognizer))
    monkeypatch.setattr(audio, "_vosk_pcm", lambda *_: bytearray(9000))
    request = {"audio_base64": base64.b64encode(clip()).decode(), "engine": "vosk", "model": "polish", "language": "pl"}
    for _ in range(2):
        result = audio.transcribe(request)
        assert (result["text"], result["language"], result["engine"]) == ("pierwsza druga", "pl", "vosk")
    assert loads == [str(model)] and len(sessions) == 2
    assert all([len(chunk) for chunk in session.chunks] == [8000, 1000] for session in sessions)
    with pytest.raises(audio.SpeechError, match="Vosk accepts only"):
        audio.transcribe(dict(request, beam_size=2))
    monkeypatch.setitem(sys.modules, "vosk", None)
    with pytest.raises(audio.SpeechError) as unavailable:
        audio.transcribe(request)
    assert unavailable.value.status == 503


def test_real_resample_has_no_padding_and_obeys_limit(monkeypatch):
    pytest.importorskip("av")
    assert len(audio._vosk_pcm(clip(), "audio/wav")) == 1600 * 2
    monkeypatch.setattr(audio, "MAX_AUDIO_SECONDS", 0.05)
    with pytest.raises(audio.SpeechError) as excessive:
        audio._vosk_pcm(clip(), "audio/wav")
    assert excessive.value.code == "SPEECH_AUDIO_INVALID"
