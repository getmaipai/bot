"""M-R2's analysis: onset, amplitude, peak velocity and settling from a state-feed
trace, and the stall verdict, as pure functions over synthetic traces."""

from __future__ import annotations

import math

import pytest

from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.reachy_mini_renderer import build_steps
from maipai_body.hal.seam import AntennaPositions, HeadPose, StateFrame
from maipai_body.measure.motion import (
    Sample,
    analyze_motion,
    axis_peaks_exceeding_limits,
    commanded_peak_rad,
    sample_from_frame,
    stall_verdict,
)

MS = 1_000_000


def _s(t_ms: float, yaw: float = 0.0, pitch: float = 0.0, left: float = 0.0) -> Sample:
    return Sample(
        t_received_ns=int(t_ms * MS), pitch=pitch, roll=0.0, yaw=yaw, left=left, right=0.0
    )


def _ramp(start_ms: float, yaw_peak: float, steps: int = 10, dt_ms: float = 33.0) -> list[Sample]:
    """A ramp from 0 to yaw_peak then still frames, 33 ms apart."""
    trace = [_s(start_ms + i * dt_ms, yaw=yaw_peak * (i + 1) / steps) for i in range(steps)]
    last = trace[-1].t_received_ns / MS
    trace += [_s(last + (i + 1) * dt_ms, yaw=yaw_peak) for i in range(8)]
    return trace


def test_onset_is_the_first_frame_past_the_threshold_measured_from_the_cue():
    baseline = _s(0)
    trace = _ramp(100, yaw_peak=0.5)
    result = analyze_motion(trace, baseline, t_cue_ns=0 * MS, t_command_ns=10 * MS)
    assert result.cue_to_command_ms == pytest.approx(10.0)
    # first ramp frame is 0.05 rad (> 0.01 threshold) at t=100 ms
    assert result.cue_to_onset_ms == pytest.approx(100.0)
    assert result.command_to_onset_ms == pytest.approx(90.0)


def test_amplitude_is_the_largest_distance_from_the_baseline():
    result = analyze_motion(_ramp(100, 0.5), _s(0), t_cue_ns=0, t_command_ns=0)
    assert result.amplitude_rad == pytest.approx(0.5)


def test_peak_velocity_is_the_largest_step_over_its_own_interval():
    result = analyze_motion(_ramp(100, 0.5), _s(0), t_cue_ns=0, t_command_ns=0)
    # 0.05 rad per 33 ms between ramp frames
    assert result.peak_velocity_rad_s == pytest.approx(0.05 / 0.033, rel=0.05)


def test_settling_is_five_consecutive_still_frames_after_onset():
    trace = _ramp(100, 0.5)
    result = analyze_motion(trace, _s(0), t_cue_ns=0, t_command_ns=0)
    ramp_end_ms = trace[9].t_received_ns / MS
    # the 5th still frame after the ramp ends
    assert result.cue_to_settled_ms == pytest.approx(ramp_end_ms + 5 * 33.0)


def test_a_head_that_never_moves_has_no_onset_and_no_settling():
    trace = [_s(100 + i * 33) for i in range(20)]
    result = analyze_motion(trace, _s(0), t_cue_ns=0, t_command_ns=0)
    assert result.cue_to_onset_ms is None
    assert result.command_to_onset_ms is None
    assert result.cue_to_settled_ms is None
    assert result.amplitude_rad == 0.0


def test_an_empty_trace_is_reported_as_an_error_row_not_a_crash():
    result = analyze_motion([], _s(0), t_cue_ns=0, t_command_ns=0)
    assert result.error == "no frames captured"


def test_sample_from_frame_needs_both_head_and_antennas():
    frame = StateFrame.stamped(
        1, head_pose=HeadPose(yaw=0.2), antennas=AntennaPositions(left=0.1, right=-0.1)
    )
    sample = sample_from_frame(frame)
    assert sample is not None
    assert (sample.yaw, sample.left, sample.right) == (0.2, 0.1, -0.1)
    assert sample_from_frame(StateFrame.stamped(2, head_pose=HeadPose())) is None


def test_commanded_peak_is_the_largest_absolute_axis_value_across_the_steps():
    steps = build_steps("tilt", REACHY_MINI_PROFILE)
    peak = commanded_peak_rad(steps)
    assert peak > 0.0
    assert commanded_peak_rad(build_steps("stop", REACHY_MINI_PROFILE)) == 0.0


def test_axis_peaks_exceeding_limits_names_the_axis_and_its_declared_bound():
    inside = [_s(0, yaw=0.2)]
    assert axis_peaks_exceeding_limits(REACHY_MINI_PROFILE, inside) == []
    beyond_pitch = [_s(0, pitch=math.radians(41))]
    exceeded = axis_peaks_exceeding_limits(REACHY_MINI_PROFILE, beyond_pitch)
    assert [name for name, _peak, _bound in exceeded] == ["head_pitch"]


def test_stall_verdict_is_reached_when_most_of_the_commanded_motion_happened():
    assert stall_verdict(commanded_rad=0.4, achieved_rad=0.39) == "reached"
    assert stall_verdict(commanded_rad=0.4, achieved_rad=0.1) == "stalled"


def test_stall_verdict_has_nothing_to_judge_for_a_primitive_that_commands_no_motion():
    assert stall_verdict(commanded_rad=0.0, achieved_rad=0.0) == "no_motion_commanded"


def test_time_to_still_is_zero_when_the_head_is_already_still_at_the_cue():
    from maipai_body.measure.motion import time_to_still

    trace = [_s(100 + i * 33) for i in range(10)]
    assert time_to_still(trace, after_ns=100 * MS) == pytest.approx(0.0)


def test_time_to_still_counts_from_the_cue_to_the_first_run_of_still_frames():
    from maipai_body.measure.motion import time_to_still

    moving = [_s(100 + i * 33, yaw=0.05 * (i + 1)) for i in range(5)]
    still = [_s(300 + i * 33, yaw=0.30) for i in range(8)]
    # the last step (0.25 to 0.30) is motion; the run of five still steps starts at t=300 ms
    result = time_to_still(moving + still, after_ns=100 * MS)
    assert result == pytest.approx(300 - 100)


def test_time_to_still_ignores_frames_before_the_cue():
    from maipai_body.measure.motion import time_to_still

    before = [_s(i * 33, yaw=0.1 * i) for i in range(5)]  # moving, but before the cue
    after = [_s(500 + i * 33, yaw=0.5) for i in range(8)]
    assert time_to_still(before + after, after_ns=500 * MS) == pytest.approx(0.0)


def test_time_to_still_is_none_if_the_head_never_settles():
    from maipai_body.measure.motion import time_to_still

    trace = [_s(100 + i * 33, yaw=0.05 * i) for i in range(20)]
    assert time_to_still(trace, after_ns=100 * MS) is None
