"""M-R3: wake and direction of arrival on this array. Hardware-only: run it on the unit.

Design record section 12 and ``docs/dev.md`` section 11 (M-08's gates): false
accepts per hour and recall for the wake model on the daemon's 16 kHz path,
direction-of-arrival error at eight bearings, and barge-in through the
chip's echo cancellation with the hub's speech playing at conversation level.
The real wake model is needed: point ``--models-dir`` (or
``MAIPAI_WAKEWORD_MODELS_DIR``) at a directory holding ``melspectrogram.onnx``,
``embedding_model.onnx`` and ``trained_hey_maipai_v2.onnx``. The daemon must
be running on the unit with its media on, and the body app stopped (two
readers of the microphone would fight). Each part writes its own file; run
``report`` last to gather them.

On the unit, the scripts run from a copy of ``body/scripts`` with the apps venv
that ``scripts/install-reachy.sh`` installed the wheel into (``uv run`` cannot
resolve there; the lockfile is scoped to the dev Mac)::

    scp -r body/scripts pollen@<robot address>:maipai-scripts
    ssh pollen@<robot address>
    cd maipai-scripts/..    # any directory; --out-dir defaults to ./measurements

Then, on the unit::

    # 1. False accepts: leave the unit listening to ordinary room audio
    #    (a television at room level is the dev.md gate), at least 2 hours.
    /venvs/apps_venv/bin/python scripts/measure_mr3_wake_doa.py false-accepts --hours 2.5 \\
        --label "television news at room level"

    # 2. Recall, each condition with ten attempts or more. Say the wake phrase
    #    when prompted; for near_miss say the confusable phrases instead.
    /venvs/apps_venv/bin/python scripts/measure_mr3_wake_doa.py \
        recall --condition quiet_1m --attempts 10
    /venvs/apps_venv/bin/python scripts/measure_mr3_wake_doa.py \
        recall --condition tv_3m --attempts 10
    /venvs/apps_venv/bin/python scripts/measure_mr3_wake_doa.py \
        recall --condition near_miss --attempts 10

    # 3. Direction of arrival: a person (or a speaker playing speech) at each of
    #    eight bearings, 1 m from the unit. 0 is straight ahead, bearings
    #    increase counter-clockwise seen from above (90 is the robot's left).
    /venvs/apps_venv/bin/python scripts/measure_mr3_wake_doa.py doa --dwell-s 3

    # 4. Barge-in: speech plays through the unit's speaker at the level you will
    #    use in conversation (set it with the daemon's volume, note it in
    #    --note); first a control with nobody speaking, then wake attempts.
    /venvs/apps_venv/bin/python scripts/measure_mr3_wake_doa.py barge-in \\
        --playback-wav <speech.wav> --attempts 10 --note "volume <level>"

    # 5. Gather the parts and print the gates; --record adds the section to
    #    docs/dev/measurements.md.
    /venvs/apps_venv/bin/python scripts/measure_mr3_wake_doa.py report --record

Output: ``<out-dir>/M-R3-unit-<part>-<date>.json`` (default ``measurements/``).
No audio is stored, only counts, scores and angles.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import threading
import time
from pathlib import Path

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.measure.report import daemon_version_from, wake_doa_section
from maipai_body.measure.run_header import new_run_header, record_section, write_run
from maipai_body.measure.turn_driver import load_utterance
from maipai_body.measure.wake_doa import (
    assemble_parts,
    collect_doa,
    count_false_accepts,
    eight_bearings,
    listen_for_wake,
    play_samples,
    summarize_bearing,
)
from maipai_body.speech.capture import AudioCapture
from maipai_body.speech.models import EMBEDDING, MELSPECTROGRAM, WAKE_PHRASE
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.wake import OpenWakeWordEngine, WakeScorer

MEASUREMENTS_MD = Path(__file__).parent.parent.parent / "docs" / "dev" / "measurements.md"
CONDITIONS = ("quiet_1m", "tv_3m", "near_miss")


def _engine(models_dir: Path) -> OpenWakeWordEngine:
    return OpenWakeWordEngine(
        wake_phrase_model=models_dir / WAKE_PHRASE.file,
        melspec_model=models_dir / MELSPECTROGRAM.file,
        embedding_model=models_dir / EMBEDDING.file,
    )


def _prompt(message: str) -> None:
    input(f"{message} Press Enter to start the listening window: ")


def _header(args) -> dict:
    return new_run_header(
        row="M-R3",
        mode="unit",
        profile_id=REACHY_MINI_PROFILE.id,
        daemon_version=daemon_version_from(args.host, args.port),
        image_release=args.image_release,
    )


def _prompted_attempts(capture, scorer, attempts: int, window_s: float, message: str) -> list[dict]:
    results = []
    for i in range(attempts):
        _prompt(f"Attempt {i + 1} of {attempts}: {message}.")
        results.append(listen_for_wake(capture, scorer, window_s=window_s))
        print(
            f"  -> {'woke' if results[-1]['fired'] else 'no wake'} "
            f"(best score {results[-1]['best_score']:.2f})",
            flush=True,
        )
    return results


def _report(args) -> None:
    rows = [
        json.loads(path.read_text())["rows"][0]
        for path in sorted(args.out_dir.glob("M-R3-unit-*.json"))
    ]
    if not rows:
        raise SystemExit(f"no M-R3 part files under {args.out_dir}")
    parts = assemble_parts(rows)
    for name, gate in parts["gates"].items():
        print(f"{name}: {gate['pass']} ({gate['value']}; {gate['gate']})")
    if args.record:
        written = record_section(
            MEASUREMENTS_MD,
            "## M-R3: wake and direction of arrival (unit)",
            wake_doa_section(_header(args), parts),
            fallback_dir=args.out_dir,
        )
        print(f"recorded in {written}")


def main() -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", default="localhost")
    common.add_argument("--port", type=int, default=8000)
    common.add_argument(
        "--models-dir", type=Path, default=os.environ.get("MAIPAI_WAKEWORD_MODELS_DIR")
    )
    common.add_argument("--image-release", default=None)
    common.add_argument("--out-dir", type=Path, default=Path("measurements"))
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="part", required=True)

    fa = sub.add_parser("false-accepts", parents=[common])
    fa.add_argument("--hours", type=float, required=True)
    fa.add_argument("--label", required=True, help="what the room sounded like, in words")

    rc = sub.add_parser("recall", parents=[common])
    rc.add_argument("--condition", choices=CONDITIONS, required=True)
    rc.add_argument("--attempts", type=int, default=10)
    rc.add_argument("--window-s", type=float, default=4.0)

    dd = sub.add_parser("doa", parents=[common])
    dd.add_argument("--dwell-s", type=float, default=3.0)
    dd.add_argument("--hz", type=float, default=20.0)

    bi = sub.add_parser("barge-in", parents=[common])
    bi.add_argument("--playback-wav", type=Path, required=True, help="16 kHz 16-bit mono speech")
    bi.add_argument("--attempts", type=int, default=10)
    bi.add_argument("--window-s", type=float, default=4.0)
    bi.add_argument("--control-s", type=float, default=60.0)
    bi.add_argument("--note", default="")

    rp = sub.add_parser("report", parents=[common])
    rp.add_argument("--record", action="store_true")

    args = parser.parse_args()
    if args.part == "report":
        _report(args)
        return
    if args.models_dir is None:
        parser.error("--models-dir (or MAIPAI_WAKEWORD_MODELS_DIR) is required")

    header = _header(args)
    client = ReachyMiniClient(REACHY_MINI_PROFILE, host=args.host, port=args.port)
    capture = AudioCapture(client)
    scorer = WakeScorer(_engine(args.models_dir), client)
    playback_thread = None
    stop_playback = threading.Event()
    playback = None
    capture.start()
    try:
        if args.part == "false-accepts":
            result = count_false_accepts(capture, scorer, duration_s=args.hours * 3600)
            row = {
                "part": "false_accepts",
                "label": args.label,
                "events": len(result["events_s"]),
                "events_s": result["events_s"],
                "listened_hours": result["duration_s"] / 3600,
            }
        elif args.part == "recall":
            attempts = _prompted_attempts(
                capture,
                scorer,
                args.attempts,
                args.window_s,
                "say the near-miss phrase"
                if args.condition == "near_miss"
                else "say the wake phrase",
            )
            row = {
                "part": "recall",
                "condition": args.condition,
                "attempts": args.attempts,
                "hits": sum(1 for a in attempts if a["fired"]),
                "results": attempts,
            }
        elif args.part == "doa":
            summaries = []
            for bearing in eight_bearings():
                _prompt(
                    f"Speak continuously from bearing {math.degrees(bearing):.0f} "
                    "degrees (0 ahead, 90 the robot's left)."
                )
                readings = collect_doa(client, dwell_s=args.dwell_s, hz=args.hz)
                summary = summarize_bearing(readings, bearing)
                summary["raw_angles_rad"] = [round(r.angle_rad, 4) for r in readings]
                summaries.append(summary)
            row = {"part": "doa", "bearings": summaries}
        else:  # barge-in
            speech = load_utterance(args.playback_wav)
            playback = AudioPlayback(client)
            playback.start()

            def loop_playback() -> None:
                while not stop_playback.is_set():
                    play_samples(
                        playback,
                        speech,
                        playback.output_samplerate(),
                        chunk_s=0.1,
                        stop=stop_playback,
                    )

            playback_thread = threading.Thread(target=loop_playback, daemon=True)
            playback_thread.start()
            time.sleep(1.0)
            control = count_false_accepts(capture, scorer, duration_s=args.control_s)
            attempts = _prompted_attempts(
                capture,
                scorer,
                args.attempts,
                args.window_s,
                "say the wake phrase over the playback",
            )
            row = {
                "part": "barge_in",
                "attempts": args.attempts,
                "hits": sum(1 for a in attempts if a["fired"]),
                "self_triggers": len(control["events_s"]),
                "control_s": control["duration_s"],
                "note": args.note,
                "results": attempts,
            }
    finally:
        stop_playback.set()
        if playback_thread is not None:
            playback_thread.join(timeout=5.0)
        if playback is not None:
            playback.stop()
        capture.stop()
        client.disconnect()

    tag = f"recall-{row['condition']}" if row["part"] == "recall" else row["part"].replace("_", "-")
    path = write_run(args.out_dir, header, [row], tag=tag)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
