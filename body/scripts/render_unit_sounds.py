"""Render the StackChan earcon family (firmware assets) deterministically.

One family, one timbre: a soft bell (a sine with a quiet second and third harmonic, a 10 ms
attack and an exponential decay). Good news rises and bad news falls, so the set sounds like a set:

    needs_you  two notes rising, insistent (first setup, waiting for an admin)
    plug_in    two notes rising, quick (the charger went in)
    charged    three notes rising (the battery is full)
    unplug     one note sliding down (the charger came out)
    offline    two notes falling (the link to Home has been down 10 s)
    goodbye    three notes falling, slow (the power key)
    shutter    a short double click (a picture is being taken)

The files are Ogg Opus, mono, 16 kHz, 24 kbps, 60 ms frames: the same encoder settings as the
five tones the firmware already ships (xiaozhi ``scripts/mp3_to_ogg.sh`` adds ``-b:a 16k``; the
frame length is the one the unit's player assumes). The encoder is ffmpeg with libopus; the
output is bit-exact so a rerun gives the same bytes. Run from ``body/``::

    uv run python scripts/render_unit_sounds.py            # writes the .ogg files and sounds.json
    uv run python scripts/render_unit_sounds.py --check    # fails if the committed files differ

``FFMPEG`` names the encoder; otherwise ``ffmpeg`` on PATH, then the Stack's own copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

RATE = 16000
PEAK = 0.55
OUT_DIR = (
    Path(__file__).resolve().parents[1] / "maipai_body/bodies/stackchan/firmware/assets/sounds"
)
STACK_FFMPEG = Path("/usr/local/maipai-home/stack/data/engines/ffmpeg/current/ffmpeg")

# Equal-tempered note frequencies in Hz.
C5, D5, E5, G5, A5, C6 = 523.25, 587.33, 659.26, 783.99, 880.00, 1046.50
A4 = 440.00


def _bell(
    freq: float, length_s: float, decay_s: float, glide_to: float | None = None
) -> np.ndarray:
    """One soft bell note: harmonics 1, 2, 3 at 1, 0.28, 0.08; 10 ms attack; exponential decay."""
    n = int(length_s * RATE)
    t = np.arange(n) / RATE
    if glide_to is None:
        phase = 2 * np.pi * freq * t
    else:  # a smooth slide in pitch: the phase is the integral of a linear frequency ramp
        slide = freq + (glide_to - freq) * (t / length_s) ** 0.8
        phase = 2 * np.pi * np.cumsum(slide) / RATE
    wave = np.sin(phase) + 0.28 * np.sin(2 * phase) + 0.08 * np.sin(3 * phase)
    attack = np.minimum(1.0, t / 0.010)
    envelope = attack * np.exp(-t / decay_s)
    release = np.minimum(1.0, (length_s - t) / 0.030)  # a 30 ms fade so the cut never clicks
    return wave * envelope * release


def _place(parts: list[tuple[float, np.ndarray]], total_s: float) -> np.ndarray:
    out = np.zeros(int(total_s * RATE))
    for start_s, part in parts:
        start = int(start_s * RATE)
        end = min(len(out), start + len(part))
        out[start:end] += part[: end - start]
    return out


def needs_you() -> np.ndarray:
    return _place([(0.0, _bell(G5, 0.30, 0.16)), (0.20, _bell(C6, 0.55, 0.22))], 0.80)


def plug_in() -> np.ndarray:
    return _place([(0.0, _bell(C5, 0.20, 0.10)), (0.11, _bell(G5, 0.34, 0.14))], 0.46)


def charged() -> np.ndarray:
    return _place(
        [
            (0.0, _bell(C5, 0.24, 0.12)),
            (0.15, _bell(E5, 0.24, 0.12)),
            (0.30, _bell(G5, 0.55, 0.22)),
        ],
        0.88,
    )


def unplug() -> np.ndarray:
    return _place([(0.0, _bell(G5, 0.46, 0.20, glide_to=C5))], 0.48)


def offline() -> np.ndarray:
    return _place([(0.0, _bell(E5, 0.30, 0.15)), (0.20, _bell(A4, 0.50, 0.20))], 0.72)


def goodbye() -> np.ndarray:
    return _place(
        [
            (0.0, _bell(G5, 0.32, 0.16)),
            (0.22, _bell(E5, 0.32, 0.16)),
            (0.44, _bell(C5, 0.52, 0.26)),
        ],
        0.98,
    )


def shutter() -> np.ndarray:
    """Two quick clicks, 70 ms apart (open, close): a noise tick and a short low knock."""
    rng = np.random.default_rng(20261113)
    total = int(0.42 * RATE)
    out = np.zeros(total)

    def click(at_s: float, gain: float) -> None:
        start = int(at_s * RATE)
        n = int(0.060 * RATE)
        t = np.arange(n) / RATE
        tick = rng.standard_normal(n) * np.exp(-t / 0.003)
        # a one-pole low-pass on the noise keeps the click soft on the small speaker
        soft = np.empty(n)
        acc = 0.0
        for i in range(n):
            acc += 0.45 * (tick[i] - acc)
            soft[i] = acc
        knock = np.sin(2 * np.pi * 420 * t) * np.exp(-t / 0.016)
        piece = gain * (0.7 * soft + 1.0 * knock)
        out[start : start + n] += piece

    click(0.02, 1.0)
    click(0.09, 0.7)
    return out


EARCONS = {
    "needs_you": needs_you,
    "plug_in": plug_in,
    "charged": charged,
    "unplug": unplug,
    "offline": offline,
    "goodbye": goodbye,
    "shutter": shutter,
}

# The five tones already in the firmware, played by name through the same tool.
SHIPPED = {
    "success": "xiaozhi common/success.ogg (rising, 1.0 s): back online, ready",
    "popup": "xiaozhi common/popup.ogg (rising, 0.5 s): the wake word",
    "vibration": "xiaozhi common/vibration.ogg (0.8 s): the offline tap tone",
    "exclamation": "xiaozhi common/exclamation.ogg (0.9 s): an error",
    "low_battery": "xiaozhi common/low_battery.ogg (1.0 s): the battery is low",
}


def find_ffmpeg() -> str:
    env = os.environ.get("FFMPEG")
    if env:
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    if STACK_FFMPEG.exists():
        return str(STACK_FFMPEG)
    raise SystemExit(
        "No ffmpeg with libopus was found. Install ffmpeg or set FFMPEG to its path, then retry."
    )


def encode_ogg(
    samples: np.ndarray, out: Path, ffmpeg: str, *, bitrate: str = "24k", in_rate: int = RATE
) -> None:
    """Float samples in -1..1 (at ``in_rate``) to Ogg Opus mono 16 kHz, 60 ms frames, bit-exact."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "in.raw"
        raw.write_bytes(pcm)
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-y",
                "-f",
                "s16le",
                "-ar",
                str(in_rate),
                "-ac",
                "1",
                "-i",
                str(raw),
                "-c:a",
                "libopus",
                "-b:a",
                bitrate,
                "-ac",
                "1",
                "-ar",
                str(RATE),
                "-frame_duration",
                "60",
                "-application",
                "voip",
                "-map_metadata",
                "-1",
                "-fflags",
                "+bitexact",
                "-flags:a",
                "+bitexact",
                str(out),
            ],
            check=True,
        )


def normalise(samples: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(samples)))
    return samples * (PEAK / peak) if peak > 0 else samples


def render(out_dir: Path, ffmpeg: str) -> dict[str, dict[str, object]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, object]] = {}
    for name, make in EARCONS.items():
        samples = normalise(make())
        path = out_dir / f"snd_{name}.ogg"
        encode_ogg(samples, path, ffmpeg)
        data = path.read_bytes()
        manifest[name] = {
            "file": path.name,
            "seconds": round(len(samples) / RATE, 2),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return manifest


def manifest_text(manifest: dict[str, dict[str, object]]) -> str:
    doc = {
        "about": "Rendered by body/scripts/render_unit_sounds.py (a synthesized soft bell).",
        "format": "Ogg Opus, mono, 16 kHz, 24 kbps, 60 ms frames",
        "earcons": manifest,
        "shipped": SHIPPED,
    }
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when the committed files differ")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    ffmpeg = find_ffmpeg()
    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            fresh = render(Path(tmp), ffmpeg)
            text = manifest_text(fresh)
        committed = (args.out / "sounds.json").read_text()
        if committed != text:
            print(
                "The committed earcons differ from a fresh render. Rerun without --check.",
                file=sys.stderr,
            )
            return 1
        print("ok: the committed earcons match a fresh render")
        return 0
    manifest = render(args.out, ffmpeg)
    (args.out / "sounds.json").write_text(manifest_text(manifest))
    for name, row in manifest.items():
        print(f"{name:10s} {row['seconds']:.2f} s {row['bytes']:5d} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
