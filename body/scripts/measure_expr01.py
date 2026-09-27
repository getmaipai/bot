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
from dataclasses import dataclass, field
from pathlib import Path

import requests

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.primitives import PRIMITIVE_NAMES
from maipai_body.expression.reachy_mini_renderer import render
from maipai_body.hal.seam import AntennaPositions, HeadPose

ONSET_THRESHOLD_RAD = 0.01
SETTLE_THRESHOLD_RAD = 0.003
SETTLE_CONSECUTIVE_FRAMES = 5
POST_COMMAND_WINDOW_S = 1.5


@dataclass
class Sample:
    t_received_ns: int
    pitch: float
    roll: float
    yaw: float
    left: float
    right: float


@dataclass
class FeedRecorder:
    samples: list[Sample] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)

    def run(self, client: ReachyMiniClient) -> None:
        feed = client.state_feed(frequency=30.0)
        try:
            for frame in feed:
                if frame.head_pose is not None and frame.antennas is not None:
                    self.samples.append(
                        Sample(
                            t_received_ns=frame.t_received_ns,
                            pitch=frame.head_pose.pitch,
                            roll=frame.head_pose.roll,
                            yaw=frame.head_pose.yaw,
                            left=frame.antennas.left,
                            right=frame.antennas.right,
                        )
                    )
                if self._stop.is_set():
                    break
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()


def _pose_distance(a: Sample, b: Sample) -> float:
    return max(
        abs(a.pitch - b.pitch),
        abs(a.roll - b.roll),
        abs(a.yaw - b.yaw),
        abs(a.left - b.left),
        abs(a.right - b.right),
    )


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
    result: dict = {"primitive": primitive, "frames": len(trace)}
    if not trace or baseline is None:
        result["error"] = "no frames captured"
        return result

    onset_ns = None
    amplitude = 0.0
    peak_velocity = 0.0
    settle_ns = None
    consecutive_still = 0
    prev = baseline
    prev_t = baseline.t_received_ns

    for sample in trace:
        delta = _pose_distance(sample, baseline)
        amplitude = max(amplitude, delta)
        dt_s = max((sample.t_received_ns - prev_t) / 1e9, 1e-6)
        velocity = _pose_distance(sample, prev) / dt_s
        peak_velocity = max(peak_velocity, velocity)

        if onset_ns is None and delta > ONSET_THRESHOLD_RAD:
            onset_ns = sample.t_received_ns

        step_delta = _pose_distance(sample, prev)
        if onset_ns is not None:
            if step_delta < SETTLE_THRESHOLD_RAD:
                consecutive_still += 1
                if consecutive_still >= SETTLE_CONSECUTIVE_FRAMES and settle_ns is None:
                    settle_ns = sample.t_received_ns
            else:
                consecutive_still = 0

        prev = sample
        prev_t = sample.t_received_ns

    result["cue_to_onset_ms"] = (onset_ns - t_cue_ns) / 1e6 if onset_ns is not None else None
    result["amplitude_rad"] = amplitude
    result["peak_velocity_rad_s"] = peak_velocity
    result["cue_to_settled_ms"] = (settle_ns - t_cue_ns) / 1e6 if settle_ns is not None else None
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    status = requests.get(f"http://{args.host}:{args.port}/api/daemon/status", timeout=5).json()
    daemon_version = status["version"]

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
        "# Bench measurements",
        "",
        "Recorded per `dev.md` section 11's header: mode, daemon version, profile id, date.",
        "Never a hostname, never a household recording.",
        "",
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
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
