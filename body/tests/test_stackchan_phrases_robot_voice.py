import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import render_unit_phrases as renderer  # noqa: E402


def _wav() -> bytes:
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes((np.sin(np.arange(16000) * 0.04) * 9000).astype("<i2").tobytes())
    return buf.getvalue()


def test_voice_render_uses_each_text_and_normalizer_and_private_manifest(tmp_path, monkeypatch):
    seen = []
    normalized = []

    def synthesize(tts, text, voice_id):
        seen.append((text, voice_id))
        return renderer._decode(_wav())

    original = renderer.normalise_wav

    def normalize(data):
        normalized.append(data)
        return original(data)

    monkeypatch.setattr(renderer, "synthesize_robot_voice", synthesize)
    monkeypatch.setattr(renderer, "normalise_wav", normalize)
    monkeypatch.setattr(
        renderer, "encode_ogg", lambda samples, path, ffmpeg, **kwargs: path.write_bytes(b"ogg")
    )
    renderer._render_robot_voice("http://hub", "voice-house", tmp_path / "clips", "ffmpeg")

    expected = [text for variants in renderer.PHRASES.values() for text in variants]
    assert seen == [(text, "voice-house") for text in expected]
    assert len(normalized) == len(expected)
    manifest = json.loads((tmp_path / "clips/phrases.json").read_text())
    assert manifest["voice"] == {"id": "voice-house", "engine": "chatterbox-turbo"}
    assert len(manifest["clips"]) == len(expected)
    assert all("reference" not in json.dumps(clip).lower() for clip in manifest["clips"])
    assert (tmp_path / "clips/voice.sha256").exists()


def test_out_inside_repository_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(renderer, "_inside_repo", lambda path: True)
    assert (
        renderer.main(["--tts", "http://hub", "--voice-id", "voice-x", "--out", str(tmp_path)]) == 1
    )
    assert "outside the git work tree" in capsys.readouterr().err


def test_unavailable_voice_leaves_no_output(tmp_path, monkeypatch, capsys):
    out = tmp_path / "clips"

    def unavailable(*args):
        raise renderer.VoiceUnavailable

    monkeypatch.setattr(renderer, "synthesize_robot_voice", unavailable)
    monkeypatch.setattr(renderer, "find_ffmpeg", lambda: "ffmpeg")
    assert (
        renderer.main(["--tts", "http://hub", "--voice-id", "voice-gone", "--out", str(out)]) == 1
    )
    assert not out.exists()
    assert (
        capsys.readouterr().out.strip()
        == "the robot's voice voice-gone is not available; nothing was rendered"
    )


def test_voice_digest_tracks_id_and_text(monkeypatch):
    original = renderer._voice_text_digest("voice-a")
    assert renderer._voice_text_digest("voice-b") != original
    monkeypatch.setitem(renderer.PHRASES, "no_wifi", ["Changed text"])
    assert renderer._voice_text_digest("voice-a") != original
