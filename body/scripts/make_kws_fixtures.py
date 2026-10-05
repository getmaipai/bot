"""Rung 1 fixtures: SYNTHESIZED speech for the keyword spotter's tests. Not recordings.

Writes 16 kHz mono 16-bit wavs and ``manifest.json`` into
``tests/fixtures/kws/``: every phrase of the closed command list
(``link.commands.COMMAND_PHRASES``) and a list of near misses, each said by
two Piper voices through sherpa-onnx's own TTS. Real-microphone recordings of
the same lists are what the unit measurement needs (`measure_kws.py`);
nothing here stands in for them.

The voices are ``vits-piper-en_US-amy-low`` and ``vits-piper-en_US-ryan-medium``
from k2-fsa/sherpa-onnx's ``tts-models`` release; unpack them somewhere and
pass the two directories::

    uv run --no-sync python scripts/make_kws_fixtures.py \\
        --voice /path/vits-piper-en_US-amy-low --voice /path/vits-piper-en_US-ryan-medium

Needs the ``kws`` extra (sherpa-onnx) and scipy (the ``voice`` extra).
"""

from __future__ import annotations

import argparse
import glob
import json
import wave
from math import gcd
from pathlib import Path

import numpy as np

from maipai_body.link.commands import COMMAND_PHRASES

OUT = Path(__file__).parent.parent / "tests" / "fixtures" / "kws"
# Phrasings that contain a command phrase but are not on the closed list.
EXTRA_COMMAND_UTTERANCES = {"stop": ["stop it"], "louder": ["a little louder"]}
NEAR_MISSES = [
    "step", "shop", "quiet", "lauder", "tire", "are you corrected", "chop", "bolder",
    "dimmer", "play some music", "tell me a story", "hey my bike", "what is the weather",
    "are you happy", "turn on the light", "timber", "time it", "what is it", "who are you",
    "are you there", "hold the door", "good morning", "thank you", "what is your name",
]  # fmt: skip


def _slug(text: str) -> str:
    return text.replace(" ", "_")


def _write(path: Path, samples: np.ndarray) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(pcm.tobytes())


def main() -> None:
    import sherpa_onnx
    from scipy.signal import resample_poly

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--voice", action="append", required=True, help="a Piper voice directory")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for voice_dir in args.voice:
        voice = Path(voice_dir).name.removeprefix("vits-piper-en_US-")
        model = glob.glob(f"{voice_dir}/*.onnx")[0]
        tts = sherpa_onnx.OfflineTts(
            sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=model,
                        tokens=f"{voice_dir}/tokens.txt",
                        data_dir=f"{voice_dir}/espeak-ng-data",
                    ),
                    num_threads=2,
                )
            )
        )
        jobs = []
        for command, phrases in COMMAND_PHRASES.items():
            for phrase in (*phrases, *EXTRA_COMMAND_UTTERANCES.get(command.value, [])):
                jobs.append(("command", command.value, phrase))
        jobs += [("near_miss", None, phrase) for phrase in NEAR_MISSES]
        for kind, command, phrase in jobs:
            audio = tts.generate(phrase, sid=0, speed=1.0)
            g = gcd(16000, audio.sample_rate)
            x = resample_poly(
                np.array(audio.samples, np.float32), 16000 // g, audio.sample_rate // g
            )
            name = f"{voice}__{_slug(phrase)}.wav"
            _write(OUT / name, x)
            entries.append(
                {"file": name, "kind": kind, "command": command, "phrase": phrase, "voice": voice}
            )
    manifest = {
        "synthesized": True,
        "generator": "scripts/make_kws_fixtures.py",
        "fixtures": entries,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(entries)} fixtures to {OUT}")


if __name__ == "__main__":
    main()
