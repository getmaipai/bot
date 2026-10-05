"""G4b: the render-side logic (stamping, packing), with a fake synthesizer.

The real render runs on the owner's machine against the hub's Pocket TTS
(``scripts/render_offline_clips.py``); here the synthesizer is a stub
returning Pocket TTS's own streaming-WAV shape: a 44-byte header whose
data-chunk size is a placeholder.
"""

from __future__ import annotations

import hashlib
import struct
import zipfile

import numpy as np
import pytest

from maipai_body.speech import clip_render
from maipai_body.speech import offline_clips as oc


def _streaming_wav(n: int = 480, rate: int = 24_000) -> bytes:
    pcm = np.full(n, 2000, dtype="<i2").tobytes()
    header = (
        b"RIFF"
        + struct.pack("<I", 0xFFFFFFFF)  # placeholder sizes, as Pocket TTS writes
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", 0xFFFFFFFF)
    )
    return header + pcm


def test_normalise_wav_rewrites_a_placeholder_header_into_a_valid_wav():
    import io
    import wave

    fixed = clip_render.normalise_wav(_streaming_wav(480))
    with wave.open(io.BytesIO(fixed)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 24_000)
        assert w.getnframes() == 480


def test_normalise_wav_rejects_non_16_bit_audio():
    bad = bytearray(_streaming_wav())
    bad[34:36] = struct.pack("<H", 24)
    with pytest.raises(ValueError, match="16"):
        clip_render.normalise_wav(bytes(bad))


def test_render_all_writes_every_clip_and_stamps_the_manifest(tmp_path):
    spoken: list[str] = []

    def synth(text: str) -> bytes:
        spoken.append(text)
        return _streaming_wav()

    manifest = oc.load_manifest()
    stamped = clip_render.render_all(manifest, tmp_path, synth)

    assert spoken == [c.text for c in manifest.clips]
    for clip in stamped.clips:
        data = (tmp_path / clip.file).read_bytes()
        assert clip.sha256 == hashlib.sha256(data).hexdigest()
    oc.ClipBundle(tmp_path, stamped).verify()


def test_pack_bundle_zips_the_wavs_and_extract_round_trips_it(tmp_path):
    out = tmp_path / "rendered"
    stamped = clip_render.render_all(oc.load_manifest(), out, lambda t: _streaming_wav())
    zpath = clip_render.pack_bundle(stamped, out, tmp_path / "offline-clips.zip")

    with zipfile.ZipFile(zpath) as z:
        assert len(z.namelist()) == len(stamped.clips)
    target = oc.extract_bundle(zpath, tmp_path / "installed")
    oc.ClipBundle(target, stamped).verify()


def test_write_manifest_round_trips_through_load_manifest(tmp_path):
    stamped = clip_render.render_all(oc.load_manifest(), tmp_path, lambda t: _streaming_wav())
    path = tmp_path / "manifest.json"
    clip_render.write_manifest(stamped, path)
    assert oc.load_manifest(path) == stamped


def test_render_script_renders_then_verifies(tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "render_offline_clips",
        Path(__file__).parent.parent / "scripts" / "render_offline_clips.py",
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "_synthesizer", lambda hub, cookie: lambda text: _streaming_wav())

    out = tmp_path / "clips"
    assert (
        script.main(["render", "--out", str(out), "--hub", "http://h", "--session-cookie", "c"])
        == 0
    )
    assert "bundle sha256" in capsys.readouterr().out
    assert script.main(["verify", "--out", str(out)]) == 0

    (out / "char_A.wav").write_bytes(b"x")
    assert script.main(["verify", "--out", str(out)]) == 1
