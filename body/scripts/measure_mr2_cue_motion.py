"""M-R2: cue to motion, p50 and p95 per primitive, plus the stall probe.

Design record section 12: cue to first state-feed delta (the unit has no
encoders, so the state feed is the encoder stand-in) split at the first
command reaching the seam, amplitude, peak velocity and settling time per
primitive against the declared limits, and the stall behaviour of the head
at each fraction of an axis's limit.

Simulator (sim rows; needs ``uv run --extra sim reachy-mini-daemon --sim
--headless`` answering on port 8000; from ``body/``)::

    uv run python scripts/measure_mr2_cue_motion.py --mode sim --repeats 20 --record

On the unit (the daemon runs on the robot; run this on the robot with the
apps venv, or from any machine that reaches its port 8000, where ``--host``
is the robot's address and is never written to the output)::

    /venvs/apps_venv/bin/python scripts/measure_mr2_cue_motion.py --mode unit \\
        --image-release <OS image release> --repeats 30 --record

Then the held-head rows. The operator holds the head still when asked,
starting from the smallest fraction, and lets go on any discomfort; the head
is always sent back to neutral afterwards::

    /venvs/apps_venv/bin/python scripts/measure_mr2_cue_motion.py --mode unit \\
        --hold hand --skip-latency --record

Output: ``<out-dir>/M-R2-<mode>-<date>.json`` (default ``measurements/``) and,
with ``--record``, the sections ``M-R2: cue to motion, repeated (<mode>)`` and
``M-R2: stall probe (<mode>)`` in ``docs/dev/measurements.md`` (replaced
in place, other rows untouched). The unit's keyboard prompts need a real
terminal.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.primitives import PRIMITIVE_NAMES
from maipai_body.measure.cue_motion import run_mr2
from maipai_body.measure.report import cue_motion_section, daemon_version_from, stall_section
from maipai_body.measure.run_header import new_run_header, record_section, write_run

MEASUREMENTS_MD = Path(__file__).parent.parent.parent / "docs" / "dev" / "measurements.md"


def _confirm(message: str) -> None:
    input(f"{message}. Press Enter when you are holding it (Ctrl+C to stop): ")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--mode", choices=("sim", "unit"), required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--primitives", nargs="*", default=list(PRIMITIVE_NAMES))
    parser.add_argument("--stall-axes", nargs="*", default=["head_pitch", "head_roll", "head_yaw"])
    parser.add_argument("--stall-fractions", nargs="*", type=float, default=[0.05, 0.1, 0.2, 0.3])
    parser.add_argument(
        "--hold",
        choices=("none", "hand"),
        default="none",
        help="'hand' asks the operator to hold the head still before each stall run",
    )
    parser.add_argument("--skip-latency", action="store_true")
    parser.add_argument("--skip-stall", action="store_true")
    parser.add_argument("--image-release", default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("measurements"))
    parser.add_argument(
        "--record", action="store_true", help="also update docs/dev/measurements.md"
    )
    args = parser.parse_args()

    if args.hold == "hand" and args.mode == "sim":
        parser.error("--hold hand needs the unit: a simulator head cannot be held")

    version = daemon_version_from(args.host, args.port)
    header = new_run_header(
        row="M-R2",
        mode=args.mode,
        profile_id=REACHY_MINI_PROFILE.id,
        daemon_version=version,
        image_release=args.image_release,
    )
    client = ReachyMiniClient(REACHY_MINI_PROFILE, host=args.host, port=args.port)
    try:
        result = run_mr2(
            client,
            REACHY_MINI_PROFILE,
            repeats=0 if args.skip_latency else args.repeats,
            primitives=[] if args.skip_latency else args.primitives,
            stall_axes=[] if args.skip_stall else args.stall_axes,
            stall_fractions=args.stall_fractions,
            held=args.hold == "hand",
            confirm=_confirm if args.hold == "hand" else None,
        )
    finally:
        client.disconnect()

    path = write_run(args.out_dir, header, [result])
    print(f"wrote {path}")
    if args.record:
        if result["cue_motion"]:
            record_section(
                MEASUREMENTS_MD,
                f"## M-R2: cue to motion, repeated ({args.mode})",
                cue_motion_section(header, result["cue_motion"]),
                fallback_dir=args.out_dir,
            )
        if result["stall"]:
            record_section(
                MEASUREMENTS_MD,
                f"## M-R2: stall probe ({args.mode})",
                stall_section(header, result["stall"]),
                fallback_dir=args.out_dir,
            )
        print("recorded (docs/dev/measurements.md, or section-M-R2.md beside the run on a unit)")


if __name__ == "__main__":
    main()
