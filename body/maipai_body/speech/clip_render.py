"""G4b: render-side logic for the offline clip bundle (release time, on
a machine that can reach the hub's Pocket TTS; never run on the robot).

The network call is injected as ``synthesize(text) -> wav bytes`` so this
logic is tested with a stub; ``scripts/render_offline_clips.py`` wires
the real ``POST /api/tts``.
"""

from __future__ import annotations

import io
import wave
import zipfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from maipai_body.model_assets import _sha256_of
from maipai_body.speech.offline_clips import Manifest, manifest_to_json
from maipai_body.speech.tts_playback import _WAV_HEADER_BYTES, _parse_wav_header


def normalise_wav(streamed: bytes) -> bytes:
    """Rewrites Pocket TTS's streaming WAV (a placeholder data-chunk size
    in the header, the same quirk G7's player works around) into a
    standard WAV with true sizes, 16-bit mono."""
    if len(streamed) < _WAV_HEADER_BYTES:
        raise ValueError("audio shorter than a WAV header")
    rate, channels, bits = _parse_wav_header(streamed[:_WAV_HEADER_BYTES])
    if bits != 16:
        raise ValueError(f"expected 16-bit audio, got {bits}")
    pcm = streamed[_WAV_HEADER_BYTES:]
    pcm = pcm[: len(pcm) - (len(pcm) % (2 * channels))]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def render_all(manifest: Manifest, out_dir: Path, synthesize: Callable[[str], bytes]) -> Manifest:
    """Renders every clip into ``out_dir`` and returns the manifest
    stamped with each file's sha256."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamped = []
    for clip in manifest.clips:
        path = out_dir / clip.file
        path.write_bytes(normalise_wav(synthesize(clip.text)))
        stamped.append(replace(clip, sha256=_sha256_of(path)))
    return replace(manifest, clips=tuple(stamped))


def write_manifest(manifest: Manifest, path: Path) -> None:
    path.write_text(manifest_to_json(manifest))


def pack_bundle(manifest: Manifest, clips_dir: Path, zip_path: Path) -> Path:
    """Zips the clip files, flat, in manifest order."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for clip in manifest.clips:
            z.write(clips_dir / clip.file, arcname=clip.file)
    return zip_path
