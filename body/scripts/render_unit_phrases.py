"""Render the sixteen local offline phrases the StackChan says by itself (tier 2).

When the wake word fires and the unit has no link to Home, firmware patch 118 plays one of these
clips from the assets image: five groups by link state, never the same clip twice in a row. The
text below must match ``body/tests/test_stackchan_sounds.py`` (the group sizes) and patch 115.

The voice is the Stack's own speech engine with the household's default voice (today the Chatterbox
Turbo preset, Apache-2.0): our own synthesized voice, no real person. The clips are committed; the
manifest records the text, the checksum, the voice and the licence check, so a release is
reproducible from the files (speech synthesis itself is not bit-exact between runs). Run on the
machine that has the Stack, from ``body/``, against a speech engine you started yourself or the
Stack's TTS route::

    uv run python scripts/render_unit_phrases.py --tts http://127.0.0.1:18791

``--tts`` is a server that takes ``POST /tts`` (multipart ``text``) and answers a streamed 24 kHz
16-bit mono WAV: the MLX engine file ``mlx_tts_server.py`` of the Stack started by hand on a free
port, with ``HF_HUB_OFFLINE=1`` and the Stack's model folder as ``HF_HOME``. Listen to every clip
before a release.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import wave
from pathlib import Path

import numpy as np
import requests
from render_unit_sounds import RATE, encode_ogg, find_ffmpeg

from maipai_body.speech.clip_render import normalise_wav

OUT_DIR = (
    Path(__file__).resolve().parents[1] / "maipai_body/bodies/stackchan/firmware/assets/phrases"
)

# Group name, then the variants in play order (a round robin on the unit).
PHRASES: dict[str, list[str]] = {
    "no_wifi": [
        "I can't find the Wi-Fi.",
        "I'm not on the Wi-Fi right now.",
        "I can't see the Wi-Fi yet.",
        "The Wi-Fi isn't answering me.",
    ],
    "no_host": [
        "I can't reach my home base right now.",
        "I'm having trouble reaching home.",
        "Home isn't answering me yet.",
        "I can't get through to home just now.",
    ],
    "refused": [
        "I need to be approved again.",
        "Home needs to let me back in.",
        "I'm waiting for Home to approve me.",
    ],
    "connecting": [
        "Still connecting, one moment.",
        "Almost connected, give me a moment.",
        "Hang on, I'm still connecting.",
    ],
    "back": [
        "I'm back.",
        "I'm connected to home again.",
    ],
}

VOICE_NOTE = {
    "engine": "chatterbox-turbo",
    "model": "mlx-community/chatterbox-turbo-fp16",
    "revision": "b2d0a13aa7cfff0a06d9acb247ae91c8f19a6d75",
    "voice": "chatterbox-turbo-voice-default",
    "licence": "Apache-2.0",
    "licence_source": "the Stack's pinned catalog record (stack/docs/components.md, "
    "data/models/manifests/chatterbox-turbo-fp16.json)",
    "licence_checked": True,
    "credit": "Chatterbox Turbo (Resemble AI), Apache-2.0, run by the MaiPai Stack; "
    "the clips are machine-synthesized speech, not a recording of a person.",
}

TARGET_RMS = 0.11  # speech level that matches the shipped tones (their RMS is 0.11 to 0.29)
PEAK_LIMIT = 0.9
PAD_S = 0.06


def _decode(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(normalise_wav(wav_bytes)), "rb") as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)
    return pcm / 32768.0, rate


def shape(samples: np.ndarray, rate: int) -> np.ndarray:
    """Trim the silence at both ends, set the level, fade the edges."""
    floor = 0.02 * float(np.max(np.abs(samples)))
    loud = np.abs(samples) > floor
    idx = np.flatnonzero(loud)
    if idx.size == 0:
        raise ValueError("the clip is silent")
    pad = int(PAD_S * rate)
    clip = samples[max(0, idx[0] - pad) : min(len(samples), idx[-1] + pad)]
    active = clip[np.abs(clip) > floor]
    rms = float(np.sqrt(np.mean(active**2)))
    clip = clip * (TARGET_RMS / rms)
    peak = float(np.max(np.abs(clip)))
    if peak > PEAK_LIMIT:
        clip = clip * (PEAK_LIMIT / peak)
    fade_in, fade_out = int(0.004 * rate), int(0.050 * rate)
    clip[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
    clip[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)
    return clip


def synthesize(tts: str, text: str) -> tuple[np.ndarray, int]:
    response = requests.post(f"{tts}/tts", files={"text": (None, text)}, timeout=(10, 180))
    response.raise_for_status()
    return _decode(response.content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tts", required=True, help="base URL of the speech engine")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    ffmpeg = find_ffmpeg()
    args.out.mkdir(parents=True, exist_ok=True)
    clips: list[dict[str, object]] = []
    for group, variants in PHRASES.items():
        for number, text in enumerate(variants, start=1):
            samples, rate = synthesize(args.tts, text)
            clip = shape(samples, rate)
            path = args.out / f"ph_{group}_{number}.ogg"
            encode_ogg(clip, path, ffmpeg, bitrate="24k", in_rate=rate)
            data = path.read_bytes()
            clips.append(
                {
                    "group": group,
                    "variant": number,
                    "text": text,
                    "file": path.name,
                    "seconds": round(len(clip) / rate, 2),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            print(f"{path.name:22s} {clips[-1]['seconds']:.2f} s {len(data):6d} bytes  {text}")
    doc = {
        "about": "Local offline phrases for the StackChan (tier 2); rendered by "
        "body/scripts/render_unit_phrases.py, played by firmware patch 118.",
        "format": f"Ogg Opus, mono, {RATE} Hz, 24 kbps, 60 ms frames",
        "voice": VOICE_NOTE,
        "clips": clips,
    }
    (args.out / "phrases.json").write_text(json.dumps(doc, indent=2) + "\n")
    print(f"{len(clips)} clips, {sum(int(c['bytes']) for c in clips)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
