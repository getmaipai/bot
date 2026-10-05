"""M-R2: cue to motion, measured through the seam on the simulator or the unit.

One harness for both benches: it needs only a ``HeadActuator`` and a
``StateFeed`` (the encoder stand-in), so the deterministic suite, the
simulator and the unit all run the same code and only the client behind
the seam differs. Nothing here picks a number; thresholds live in
``motion.py`` and the envelope in ``expression/envelope.py``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict
from typing import Any

from maipai_body.bodies.reachy_mini.envelope import axis_bounds_rad
from maipai_body.expression.reachy_mini_renderer import build_steps  # registers the renderer
from maipai_body.expression.renderers import renderer_for
from maipai_body.hal.seam import AntennaPositions, BodyProfile, HeadActuator, HeadPose
from maipai_body.measure.motion import (
    FeedRecorder,
    analyze_motion,
    axis_peaks_exceeding_limits,
    commanded_peak_rad,
    pose_distance,
    stall_verdict,
)
from maipai_body.measure.stats import summarize

_LATENCY_FIELDS = (
    "cue_to_command_ms",
    "cue_to_onset_ms",
    "command_to_onset_ms",
    "cue_to_settled_ms",
    "amplitude_rad",
    "peak_velocity_rad_s",
)
_HEAD_AXES = {"head_pitch": "pitch", "head_roll": "roll", "head_yaw": "yaw"}


class StampingClient:
    """Wraps a ``HeadActuator`` and records when its first command was issued.

    ``t_motion_command`` of the design record's M-R2: the instant the
    body hands the first command to the seam, so a cue's latency splits
    into the body's own share and the daemon-plus-motor share.
    """

    def __init__(self, inner: HeadActuator, clock: Callable[[], int] = time.monotonic_ns) -> None:
        self._inner = inner
        self._clock = clock
        self.t_first_command_ns: int | None = None

    def reset(self) -> None:
        self.t_first_command_ns = None

    def _stamp(self) -> None:
        if self.t_first_command_ns is None:
            self.t_first_command_ns = self._clock()

    def goto(self, *args, **kwargs):
        self._stamp()
        return self._inner.goto(*args, **kwargs)

    def set_target(self, *args, **kwargs):
        self._stamp()
        return self._inner.set_target(*args, **kwargs)

    def hold(self, *args, **kwargs):
        self._stamp()
        return self._inner.hold(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        if name == "_inner":
            raise AttributeError(name)
        return getattr(self._inner, name)


def _go_neutral(client: HeadActuator, duration_s: float) -> None:
    client.goto(
        pose=HeadPose(),
        antennas=AntennaPositions(left=0.0, right=0.0),
        body_yaw=0.0,
        duration_s=duration_s,
    )


def _record(client, frequency: float) -> tuple[FeedRecorder, threading.Thread]:
    recorder = FeedRecorder()
    thread = threading.Thread(target=recorder.run, args=(client, frequency), daemon=True)
    thread.start()
    return recorder, thread


def measure_primitive(
    client: HeadActuator,
    profile: BodyProfile,
    primitive: str,
    *,
    doa_angle_rad: float = 0.4,
    neutral_duration_s: float = 0.8,
    pause_s: float = 0.3,
    window_s: float = 1.5,
    frequency: float = 30.0,
    clock: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """One cue, one row: latency split, amplitude, peak velocity, settling, limits."""
    _go_neutral(client, neutral_duration_s)
    sleep(pause_s)  # from a common resting pose, not wherever the last run ended

    stamped = StampingClient(client, clock)
    recorder, thread = _record(client, frequency)
    sleep(pause_s)  # let the feed connect and a baseline accumulate
    baseline_index = len(recorder.samples)
    baseline = recorder.samples[-1] if recorder.samples else None

    t_cue_ns = clock()
    renderer_for(profile.id)(primitive, stamped, profile, doa_angle_rad=doa_angle_rad)
    sleep(window_s)
    recorder.stop()
    thread.join(timeout=2.0)

    trace = recorder.samples[baseline_index:]
    commanded = commanded_peak_rad(build_steps(primitive, profile, doa_angle_rad=doa_angle_rad))
    row: dict[str, Any] = {"primitive": primitive, "commanded_peak_rad": commanded}
    if baseline is None:
        row.update(frames=0, error="no frames captured")
        return row
    result = analyze_motion(
        trace, baseline, t_cue_ns=t_cue_ns, t_command_ns=stamped.t_first_command_ns
    )
    row.update(asdict(result))
    row["limits_exceeded"] = [
        [name, extreme, bound]
        for name, extreme, bound in axis_peaks_exceeding_limits(profile, trace)
    ]
    row["stall"] = stall_verdict(commanded_rad=commanded, achieved_rad=result.amplitude_rad)
    return row


def measure_repeated(
    client: HeadActuator,
    profile: BodyProfile,
    primitive: str,
    *,
    repeats: int,
    **pacing: Any,
) -> dict[str, Any]:
    """``repeats`` runs of one primitive, summarized as p50 and p95 per figure.

    A run that captured no frames is counted as an error and left out of
    the percentiles, never averaged in as a zero.
    """
    rows = [measure_primitive(client, profile, primitive, **pacing) for _ in range(repeats)]
    good = [row for row in rows if row.get("error") is None]
    summary: dict[str, Any] = {
        "primitive": primitive,
        "repeats": repeats,
        "errors": len(rows) - len(good),
        "no_onset": sum(1 for row in good if row["cue_to_onset_ms"] is None),
        "limits_exceeded_runs": sum(1 for row in good if row["limits_exceeded"]),
        "commanded_peak_rad": rows[0]["commanded_peak_rad"] if rows else None,
    }
    for field_name in _LATENCY_FIELDS:
        summary[field_name] = summarize(
            [row[field_name] for row in good if row[field_name] is not None]
        )
    return summary


def measure_stall_probe(
    client: HeadActuator,
    profile: BodyProfile,
    *,
    axis: str,
    fractions: Sequence[float],
    held: bool = False,
    confirm: Callable[[str], None] | None = None,
    duration_s: float = 0.4,
    neutral_duration_s: float = 0.8,
    pause_s: float = 0.3,
    window_s: float = 1.5,
    frequency: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Command one head axis to each fraction of its declared limit and see how far it got.

    ``held`` records whether someone is holding the head still (design
    record section 7: a child's hand on the head is a measurement before
    any fraction is raised); ``confirm`` is how the unit script asks the
    operator to take hold before each run. With ``held=False`` the same
    probe gives the unobstructed reference the held rows compare to. The
    head is always sent back to neutral afterwards, whatever happens.
    """
    if axis not in _HEAD_AXES:
        raise ValueError(f"axis must be one of {sorted(_HEAD_AXES)}, not {axis!r}")
    attribute = _HEAD_AXES[axis]
    _, high = axis_bounds_rad(profile.axis(axis))
    rows: list[dict[str, Any]] = []
    for fraction in fractions:
        if not 0.0 < fraction <= 1.0:
            raise ValueError(f"fraction {fraction} is outside (0, 1]")
        commanded = high * fraction
        recorder = None
        thread = None
        returned = False
        try:
            _go_neutral(client, neutral_duration_s)
            sleep(pause_s)
            if held and confirm is not None:
                confirm(f"hold the head still now: {axis} at {fraction:.2f} of its declared limit")
            recorder, thread = _record(client, frequency)
            sleep(pause_s)
            baseline_index = len(recorder.samples)
            baseline = recorder.samples[-1] if recorder.samples else None
            client.goto(
                pose=HeadPose(**{attribute: commanded}),
                antennas=AntennaPositions(left=0.0, right=0.0),
                duration_s=duration_s,
            )
            sleep(window_s)
            reached_index = len(recorder.samples)
            # Recording continues through the return so the residual is read
            # after the head has had its chance to come back.
            _go_neutral(client, neutral_duration_s)
            returned = True
            sleep(pause_s)
        finally:
            if not returned:
                _go_neutral(client, neutral_duration_s)
            if recorder is not None:
                recorder.stop()
        if thread is not None:
            thread.join(timeout=2.0)
        assert recorder is not None
        if baseline is None:
            rows.append({"axis": axis, "fraction": fraction, "held": held, "error": "no frames"})
            continue
        out_trace = recorder.samples[baseline_index:reached_index]
        achieved = max((pose_distance(s, baseline) for s in out_trace), default=0.0)
        rows.append(
            {
                "axis": axis,
                "fraction": fraction,
                "held": held,
                "commanded_rad": commanded,
                "achieved_rad": achieved,
                "verdict": stall_verdict(commanded_rad=commanded, achieved_rad=achieved),
                "residual_rad": (
                    pose_distance(recorder.samples[-1], baseline) if recorder.samples else None
                ),
                "frames": len(out_trace),
            }
        )
    return rows


def run_mr2(
    client: HeadActuator,
    profile: BodyProfile,
    *,
    repeats: int,
    primitives: Sequence[str],
    stall_axes: Sequence[str],
    stall_fractions: Sequence[float],
    held: bool,
    confirm: Callable[[str], None] | None = None,
    **pacing: Any,
) -> dict[str, list[dict[str, Any]]]:
    """The whole M-R2 row on one bench: every primitive repeated, then the stall probe."""
    cue_motion = [
        measure_repeated(client, profile, primitive, repeats=repeats, **pacing)
        for primitive in primitives
    ]
    stall: list[dict[str, Any]] = []
    for axis in stall_axes:
        stall += measure_stall_probe(
            client,
            profile,
            axis=axis,
            fractions=stall_fractions,
            held=held,
            confirm=confirm,
            **{k: v for k, v in pacing.items() if k != "doa_angle_rad"},
        )
    return {"cue_motion": cue_motion, "stall": stall}
