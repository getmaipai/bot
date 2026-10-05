"""Rung 1 keyword spotter: accuracy over wavs, and a CPU probe. Run on the unit.

LINK-STATE-01's rung 1 recognizer (`maipai_body/speech/kws.py`) has two rows
that no sandbox can fill: its CPU on the Compute Module beside the wake model,
and its false-accept rate on real microphone audio. Both are UNVERIFIED until
this runs on the unit (`docs/dev/measurements.md`, `docs/dev/offline-ladder-unit-checks.md`).

On the unit, from a copy of ``body/scripts`` with the apps venv (``uv run``
cannot resolve there), after ``pip install sherpa-onnx`` into that venv::

    # 1. Accuracy. Record the closed list and the near misses through the array
    #    (a person, 1 m, the conditions M-R3 uses), 16 kHz mono 16-bit wavs.
    #    Name a command clip <phrase with underscores>__<anything>.wav, for
    #    example stop__01.wav, what_time_is_it__07.wav; any other name is a near
    #    miss and must yield nothing. Counts only are written, never audio.
    /venvs/apps_venv/bin/python scripts/measure_kws.py accuracy --wav-dir <dir> \\
        --label "room, 1 m" --record

    # 2. False accepts on ordinary room audio: a long wav of speech that is not a
    #    command (a television at room level); every hit is a false accept.
    /venvs/apps_venv/bin/python scripts/measure_kws.py false-accepts --wav <long.wav> \\
        --label "television news at room level" --record

    # 3. CPU, as its own process so M-R1's sampler can name it. Start this, then
    #    run the pod configuration of measure_mr1_budget.py with --process kws=measure_kws.py
    #    (named in docs/dev/offline-ladder-unit-checks.md); the probe prints
    #    its own CPU seconds per audio second too.
    /venvs/apps_venv/bin/python scripts/measure_kws.py cpu --wav <utterance.wav> \\
        --seconds 3600 --record

The model is fetched on first use (``--cache-dir``, default ``./kws-cache``);
point ``MAIPAI_KWS_MODELS_DIR`` at a directory already holding the four model
files to skip the download.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path

from maipai_body.measure.kws import (
    ClipResult,
    listen_to_clip,
    load_wav_16k_mono,
    probe_cpu,
    summarize_accuracy,
)
from maipai_body.measure.run_header import record_section
from maipai_body.speech.kws import (
    KEYWORD_PHRASES,
    KeywordSpotterRecognizer,
    SherpaKeywordEngine,
    ensure_kws_model,
)

REPO = Path(__file__).resolve().parents[2]
MEASUREMENTS = REPO / "docs" / "dev" / "measurements.md"


def _model_dir(args) -> Path:
    env = os.environ.get("MAIPAI_KWS_MODELS_DIR")
    return Path(env) if env else ensure_kws_model(Path(args.cache_dir))


def _header(args) -> list[str]:
    return [
        f"- mode: `{args.mode}`",
        f"- date: {datetime.date.today().isoformat()}",
        f"- conditions: {args.label}",
    ]


def _record(args, title: str, lines: list[str]) -> None:
    section = "\n".join([f"## {title}, {datetime.date.today().isoformat()}\n", *lines, ""])
    written = record_section(MEASUREMENTS, f"## {title}", section, fallback_dir=Path(args.out_dir))
    print(f"recorded in {written}")


def accuracy(args) -> int:
    recognizer = KeywordSpotterRecognizer(SherpaKeywordEngine(_model_dir(args)))
    results = []
    for wav in sorted(Path(args.wav_dir).glob("*.wav")):
        stem = wav.stem.split("__")[0].replace("_", " ")
        expected = stem if stem in KEYWORD_PHRASES else None
        heard = listen_to_clip(recognizer, load_wav_16k_mono(wav))
        results.append(ClipResult(wav.name, expected, heard))
    if not results:
        print(f"no wavs in {args.wav_dir}", file=sys.stderr)
        return 2
    acc = summarize_accuracy(results)
    for r in results:
        if r.heard != r.expected:
            print(f"  {r.name}: expected {r.expected!r}, heard {r.heard!r}")
    print(
        f"recall {acc.recalled}/{acc.commands}, wrong command {acc.wrong_command}, "
        f"false accepts {acc.false_accepts}/{acc.near_misses}"
    )
    if args.record:
        _record(
            args,
            "Rung 1 keyword spotter: accuracy",
            [
                *_header(args),
                "",
                "| commands | recalled | wrong command | near misses | false accepts |",
                "|---|---|---|---|---|",
                f"| {acc.commands} | {acc.recalled} | {acc.wrong_command} "
                f"| {acc.near_misses} | {acc.false_accepts} |",
            ],
        )
    return 0


def false_accepts(args) -> int:
    from maipai_body.speech.capture import BLOCK_SAMPLES

    samples = load_wav_16k_mono(Path(args.wav))
    engine = SherpaKeywordEngine(_model_dir(args))
    engine.begin()
    hits = []
    for i in range(0, len(samples) - BLOCK_SAMPLES + 1, BLOCK_SAMPLES):
        tag = engine.accept(samples[i : i + BLOCK_SAMPLES])
        if tag:
            hits.append(tag)
    hours = len(samples) / 16000 / 3600
    print(f"{len(hits)} hits in {hours:.3f} h: {sorted(set(hits))}")
    if args.record:
        _record(
            args,
            "Rung 1 keyword spotter: false accepts",
            [
                *_header(args),
                f"- audio: {hours:.3f} h of speech that is not a command",
                f"- hits: {len(hits)} ({len(hits) / hours:.2f} per hour)"
                if hours
                else "- hits: n/a",
            ],
        )
    return 0


def cpu(args) -> int:
    samples = load_wav_16k_mono(Path(args.wav))
    engine = SherpaKeywordEngine(_model_dir(args))
    probe = probe_cpu(engine, samples, seconds=args.seconds, pace=not args.unpaced)
    print(
        f"{probe.cpu_s:.2f} CPU s over {probe.audio_s:.0f} audio s "
        f"({probe.real_time_factor:.3f} of one core)"
    )
    if args.record:
        pacing = "unpaced" if args.unpaced else "paced at real time"
        _record(
            args,
            "Rung 1 keyword spotter: CPU",
            [
                *_header(args),
                f"- audio: {probe.audio_s:.0f} s, {pacing}",
                f"- one core: {probe.real_time_factor:.3f} CPU s per audio s",
                "- beside the wake model: not measured here; M-R1's sampler does that",
            ],
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cache-dir", default="kws-cache")
    sub = parser.add_subparsers(dest="part", required=True)
    for name in ("accuracy", "false-accepts", "cpu"):
        p = sub.add_parser(name)
        p.add_argument("--label", required=True, help="the conditions, never a place or a person")
        p.add_argument("--record", action="store_true")
        p.add_argument("--mode", choices=("sim", "unit"), default="unit")
        p.add_argument("--out-dir", default="measurements")
        if name == "accuracy":
            p.add_argument("--wav-dir", required=True)
        else:
            p.add_argument("--wav", required=True)
        if name == "cpu":
            p.add_argument("--seconds", type=float, default=3600.0)
            p.add_argument(
                "--unpaced", action="store_true", help="as fast as it runs (the ceiling)"
            )
    args = parser.parse_args()
    return {"accuracy": accuracy, "false-accepts": false_accepts, "cpu": cpu}[args.part](args)


if __name__ == "__main__":
    raise SystemExit(main())
