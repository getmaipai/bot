"""M-R2's simulator rows: cue to first state-feed delta, amplitude, peak velocity,
settling time, per primitive, on the Reachy Mini profile's expression column.

Usage (against a running `reachy-mini-daemon --sim`, from body/)::

    uv run python scripts/measure_expr01.py --host localhost --port 8000

Streams real state frames from the daemon while a background thread
issues each primitive, in the same measurement style
``scripts/record_fixtures.py`` uses: nothing here is invented, every
number comes from a real state-feed frame timestamped with
``time.monotonic_ns()`` on receipt.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.primitives import PRIMITIVE_NAMES
from maipai_body.expression.reachy_mini_renderer import render
from maipai_body.hal.seam import AntennaPositions, HeadPose
from maipai_body.measure.motion import (
    ONSET_THRESHOLD_RAD,
    SETTLE_CONSECUTIVE_FRAMES,
    SETTLE_THRESHOLD_RAD,
    FeedRecorder,
    analyze_motion,
)
from maipai_body.measure.report import daemon_version_from
from maipai_body.measure.run_header import upsert_markdown_section

POST_COMMAND_WINDOW_S = 1.5


def _reset_to_neutral(client: ReachyMiniClient) -> None:
    """Return to a common resting pose so each primitive's amplitude is measured
    from the same reference, not from wherever the previous primitive left off.
    """
    client.goto(
        pose=HeadPose(),
        antennas=AntennaPositions(left=0.0, right=0.0),
        body_yaw=0.0,
        duration_s=0.8,
    )
    time.sleep(0.3)


def _measure_one(client: ReachyMiniClient, primitive: str) -> dict:
    _reset_to_neutral(client)
    recorder = FeedRecorder()
    thread = threading.Thread(target=recorder.run, args=(client,), daemon=True)
    thread.start()
    time.sleep(0.3)  # let the feed connect and a baseline accumulate

    baseline_index = len(recorder.samples)
    baseline = recorder.samples[-1] if recorder.samples else None

    t_cue_ns = time.monotonic_ns()
    render(primitive, client, REACHY_MINI_PROFILE, doa_angle_rad=0.4)
    time.sleep(POST_COMMAND_WINDOW_S)

    recorder.stop()
    thread.join(timeout=2.0)

    trace = recorder.samples[baseline_index:]
    if baseline is None:
        return {"primitive": primitive, "frames": 0, "error": "no frames captured"}
    motion = analyze_motion(trace, baseline, t_cue_ns=t_cue_ns, t_command_ns=None)
    if motion.error is not None:
        return {"primitive": primitive, "frames": motion.frames, "error": motion.error}
    return {
        "primitive": primitive,
        "frames": motion.frames,
        "cue_to_onset_ms": motion.cue_to_onset_ms,
        "amplitude_rad": motion.amplitude_rad,
        "peak_velocity_rad_s": motion.peak_velocity_rad_s,
        "cue_to_settled_ms": motion.cue_to_settled_ms,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    daemon_version = daemon_version_from(args.host, args.port)

    client = ReachyMiniClient(REACHY_MINI_PROFILE, host=args.host, port=args.port)

    results = []
    for primitive in PRIMITIVE_NAMES:
        print(f"measuring {primitive}...")
        results.append(_measure_one(client, primitive))

    _reset_to_neutral(client)
    client.disconnect()

    docs_dir = Path(__file__).parent.parent.parent / "docs" / "dev"
    (docs_dir / "measurements.json").write_text(json.dumps(results, indent=2) + "\n")

    _write_markdown(docs_dir / "measurements.md", daemon_version, results)
    print(f"wrote {docs_dir / 'measurements.md'}")
    for row in results:
        print(row)


def _write_markdown(path: Path, daemon_version: str, results: list[dict]) -> None:
    date = time.strftime("%Y-%m-%d", time.gmtime())
    lines = [
        f"## M-R2: cue to motion (sim), {date}",
        "",
        "- mode: `sim` (Pollen's MuJoCo daemon, `--sim`, headless or GUI viewer, no unit yet)",
        f"- daemon version: `{daemon_version}`",
        "- profile: `reachy_mini`",
        f"- onset threshold: {ONSET_THRESHOLD_RAD} rad; settle threshold: "
        f"{SETTLE_THRESHOLD_RAD} rad over {SETTLE_CONSECUTIVE_FRAMES} consecutive frames",
        "",
        "| primitive | cue→onset (ms) | amplitude (rad) | peak velocity (rad/s) | "
        "cue→settled (ms) | frames |",
        "|---|---|---|---|---|---|",
    ]
    for row in results:
        if "error" in row:
            lines.append(f"| {row['primitive']} | error: {row['error']} | | | | |")
            continue
        onset = f"{row['cue_to_onset_ms']:.1f}" if row["cue_to_onset_ms"] is not None else "n/a"
        settled = (
            f"{row['cue_to_settled_ms']:.1f}" if row["cue_to_settled_ms"] is not None else "n/a"
        )
        lines.append(
            f"| {row['primitive']} | {onset} | {row['amplitude_rad']:.4f} | "
            f"{row['peak_velocity_rad_s']:.4f} | {settled} | {row['frames']} |"
        )
    lines.append("")
    upsert_markdown_section(path, "## M-R2: cue to motion (sim)", "\n".join(lines))


if __name__ == "__main__":
    main()
