"""M-R2's analysis of a state-feed trace: onset, amplitude, peak velocity, settling.

Extracted from ``scripts/measure_expr01.py`` (same thresholds, same
rules) so the deterministic suite proves the analysis on synthetic
traces and the simulator and unit scripts share one implementation.
The unit has no encoders: the state feed is the encoder stand-in
(design record section 12), so every figure here is read from it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Literal

from maipai_body.bodies.reachy_mini.envelope import axis_bounds_rad
from maipai_body.hal.seam import BodyProfile, StateFrame

ONSET_THRESHOLD_RAD = 0.01
SETTLE_THRESHOLD_RAD = 0.003
SETTLE_CONSECUTIVE_FRAMES = 5
# A head that reached less than this share of the commanded amplitude is
# reported as stalled. A starting value for the first held-head run to
# confirm, like every fraction in the expression envelope.
STALL_REACHED_RATIO = 0.5

# state-feed sample field -> the profile axis that bounds it
_SAMPLE_AXES = (
    ("pitch", "head_pitch"),
    ("roll", "head_roll"),
    ("yaw", "head_yaw"),
    ("left", "antenna_left"),
    ("right", "antenna_right"),
)


@dataclass(frozen=True)
class Sample:
    t_received_ns: int
    pitch: float
    roll: float
    yaw: float
    left: float
    right: float


@dataclass
class MotionResult:
    frames: int
    cue_to_command_ms: float | None = None
    cue_to_onset_ms: float | None = None
    command_to_onset_ms: float | None = None
    amplitude_rad: float = 0.0
    peak_velocity_rad_s: float = 0.0
    cue_to_settled_ms: float | None = None
    error: str | None = None


def sample_from_frame(frame: StateFrame) -> Sample | None:
    if frame.head_pose is None or frame.antennas is None:
        return None
    return Sample(
        t_received_ns=frame.t_received_ns,
        pitch=frame.head_pose.pitch,
        roll=frame.head_pose.roll,
        yaw=frame.head_pose.yaw,
        left=frame.antennas.left,
        right=frame.antennas.right,
    )


def pose_distance(a: Sample, b: Sample) -> float:
    return max(
        abs(a.pitch - b.pitch),
        abs(a.roll - b.roll),
        abs(a.yaw - b.yaw),
        abs(a.left - b.left),
        abs(a.right - b.right),
    )


@dataclass
class FeedRecorder:
    """Collects typed samples from a seam ``StateFeed`` on a background thread."""

    samples: list[Sample] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)

    def run(self, client, frequency: float = 30.0) -> None:
        feed = client.state_feed(frequency=frequency)
        try:
            for frame in feed:
                sample = sample_from_frame(frame)
                if sample is not None:
                    self.samples.append(sample)
                if self._stop.is_set():
                    break
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()


def analyze_motion(
    trace: list[Sample],
    baseline: Sample,
    *,
    t_cue_ns: int,
    t_command_ns: int | None,
) -> MotionResult:
    """Onset, amplitude, peak velocity and settling of ``trace`` after the cue.

    ``cue_to_command_ms`` is the body's own share of the latency (cue
    received to the first command reaching the seam); the rest of
    ``cue_to_onset_ms`` is the daemon and the motors.
    """
    if not trace:
        return MotionResult(frames=0, error="no frames captured")

    result = MotionResult(frames=len(trace))
    if t_command_ns is not None:
        result.cue_to_command_ms = (t_command_ns - t_cue_ns) / 1e6

    onset_ns: int | None = None
    settle_ns: int | None = None
    consecutive_still = 0
    prev = baseline
    for sample in trace:
        delta = pose_distance(sample, baseline)
        result.amplitude_rad = max(result.amplitude_rad, delta)
        dt_s = max((sample.t_received_ns - prev.t_received_ns) / 1e9, 1e-6)
        step = pose_distance(sample, prev)
        result.peak_velocity_rad_s = max(result.peak_velocity_rad_s, step / dt_s)

        if onset_ns is None and delta > ONSET_THRESHOLD_RAD:
            onset_ns = sample.t_received_ns
        if onset_ns is not None:
            if step < SETTLE_THRESHOLD_RAD:
                consecutive_still += 1
                if consecutive_still >= SETTLE_CONSECUTIVE_FRAMES and settle_ns is None:
                    settle_ns = sample.t_received_ns
            else:
                consecutive_still = 0
        prev = sample

    if onset_ns is not None:
        result.cue_to_onset_ms = (onset_ns - t_cue_ns) / 1e6
        if t_command_ns is not None:
            result.command_to_onset_ms = (onset_ns - t_command_ns) / 1e6
    if settle_ns is not None:
        result.cue_to_settled_ms = (settle_ns - t_cue_ns) / 1e6
    return result


def time_to_still(
    trace: list[Sample],
    after_ns: int,
    *,
    consecutive: int = SETTLE_CONSECUTIVE_FRAMES,
    threshold: float = SETTLE_THRESHOLD_RAD,
) -> float | None:
    """Milliseconds from ``after_ns`` to the start of the first run of still frames.

    "The pose settled" after a cancel: zero when the head was already
    still at that instant, ``None`` if it never settled in the trace.
    """
    frames = [sample for sample in trace if sample.t_received_ns >= after_ns]
    steps = [pose_distance(b, a) for a, b in zip(frames, frames[1:], strict=False)]
    for i in range(len(steps) - consecutive + 1):
        if all(step < threshold for step in steps[i : i + consecutive]):
            return (frames[i].t_received_ns - after_ns) / 1e6
    return None


def commanded_peak_rad(steps) -> float:
    """The largest absolute axis value any step of a primitive commands."""
    peak = 0.0
    for step in steps:
        if step.pose is not None:
            peak = max(peak, abs(step.pose.pitch), abs(step.pose.roll), abs(step.pose.yaw))
        if step.antennas is not None:
            peak = max(peak, abs(step.antennas.left), abs(step.antennas.right))
    return peak


def axis_peaks_exceeding_limits(
    profile: BodyProfile, trace: list[Sample]
) -> list[tuple[str, float, float]]:
    """Axes whose observed extreme left the profile's declared bounds.

    Returns ``(axis name, observed extreme, violated bound)`` in radians.
    """
    exceeded: list[tuple[str, float, float]] = []
    for attribute, axis_name in _SAMPLE_AXES:
        low, high = axis_bounds_rad(profile.axis(axis_name))
        values = [getattr(sample, attribute) for sample in trace]
        if not values:
            continue
        if max(values) > high:
            exceeded.append((axis_name, max(values), high))
        elif min(values) < low:
            exceeded.append((axis_name, min(values), low))
    return exceeded


StallVerdict = Literal["reached", "stalled", "no_motion_commanded"]


def stall_verdict(*, commanded_rad: float, achieved_rad: float) -> StallVerdict:
    if commanded_rad <= 0.0:
        return "no_motion_commanded"
    if achieved_rad >= STALL_REACHED_RATIO * commanded_rad:
        return "reached"
    return "stalled"
