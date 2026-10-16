"""S-EXPR-04: deterministic gaze trajectories, one test per rule (UNMEASURED defaults)."""

from __future__ import annotations

import math

import pytest

from maipai_body.expression import gaze as g
from maipai_body.expression.gaze import FaceSample, GazeController

STEP = 0.05


def _run(ctrl, start, seconds, face_at):
    """Tick every 50 ms; ``face_at(t)`` returns a (x, y) or None. Returns outputs by time."""
    out = []
    t = start
    end = start + seconds
    while t < end - 1e-9:
        t += STEP
        pos = face_at(t)
        face = FaceSample(pos[0], pos[1], t) if pos else None
        out.append((t, ctrl.update(t, face)))
    return out


def test_inside_the_deadband_nothing_moves():
    ctrl = GazeController(now=0.0)
    out = _run(ctrl, 0.0, 1.0, lambda t: (0.05, 0.05))  # 0.025 of width, 0.025 of height
    assert ctrl.head_yaw == 0.0
    assert all(o is None or o.head_yaw == 0.0 for _, o in out)


def test_face_right_of_centre_turns_the_head_right_negative_yaw():
    ctrl = GazeController(now=0.0)
    _run(ctrl, 0.0, 0.1, lambda t: (0.4, 0.0))
    assert ctrl.head_yaw < 0.0


def test_the_deadband_is_subtracted_not_just_gated():
    ctrl = GazeController(now=0.0)
    ctrl.update(0.05, FaceSample(0.4, 0.0, 0.05))  # dx = 0.2 of width
    expected = -(0.2 - g.DEADBAND_X) * g.YAW_GAIN
    assert ctrl.head_yaw == pytest.approx(expected)


def test_pitch_never_tilts_down_past_five_degrees_while_tracking():
    ctrl = GazeController(now=0.0)
    _run(ctrl, 0.0, 3.0, lambda t: (0.0, 1.0))  # face at the bottom edge
    assert ctrl.update(3.1, FaceSample(0.0, 1.0, 3.1)).head_pitch <= 5.0 * math.pi / 180 + 1e-9


def test_send_epsilon_suppresses_sub_degree_changes():
    ctrl = GazeController(now=0.0)
    first = ctrl.update(0.05, FaceSample(0.4, 0.0, 0.05))
    # A nudge of about 0.3 degrees: below the 0.6 degree epsilon, same output object.
    nudge = 2 * (0.3 * math.pi / 180) / g.YAW_GAIN
    second = ctrl.update(0.10, FaceSample(0.0 + (g.DEADBAND_X * 2 + nudge), 0.0, 0.10))
    assert second is first


def test_head_leads_then_the_body_follows_past_the_delta_threshold():
    ctrl = GazeController(now=0.0)
    # Hold a face far left (positive yaw) long enough for the head to exceed 0.35 rad.
    out = _run(ctrl, 0.0, 6.0, lambda t: (-0.3, 0.0))
    first_body_move = next(t for t, o in out if o is not None and abs(o.body_yaw) > 1e-6)
    first_head_move = next(t for t, o in out if o is not None and abs(o.head_yaw) > 1e-6)
    assert first_head_move < first_body_move
    final = out[-1][1]
    assert final.body_yaw > 0.0
    # The body stops following once the delta is back within 0.1 rad.
    assert abs(final.head_yaw - final.body_yaw) <= g.HEAD_DELTA_CAP_RAD + 1e-9


def test_body_rate_is_capped_at_half_a_radian_per_second():
    ctrl = GazeController(now=0.0)
    out = _run(ctrl, 0.0, 4.0, lambda t: (-0.9, 0.0))
    last = 0.0
    for _, o in out:
        if o is None:
            continue
        assert o.body_yaw - last <= g.BODY_RATE_RAD_S * g.DT_CAP_S + 1e-9
        last = o.body_yaw


def test_total_yaw_stays_inside_the_caps():
    ctrl = GazeController(now=0.0)
    out = _run(ctrl, 0.0, 60.0, lambda t: (-1.0, 0.0))
    for _, o in out:
        assert abs(o.body_yaw) <= g.BODY_CAP_RAD + 1e-9
        assert abs(o.head_yaw) <= g.TOTAL_YAW_CAP_RAD + 1e-9
        assert abs(o.head_yaw - o.body_yaw) <= g.HEAD_DELTA_CAP_RAD + 1e-9


def test_detections_are_ignored_for_260_ms_after_a_body_move():
    ctrl = GazeController(now=0.0)
    _run(ctrl, 0.0, 5.0, lambda t: (-0.9, 0.0))
    moved_at = ctrl._last_body_move
    head_before = ctrl.head_yaw
    t = moved_at + 0.1  # inside the window, a body move was just made
    ctrl._last_update = moved_at
    ctrl.update(t, FaceSample(-0.9, 0.0, t))
    # The head target was not steered by this detection (the body may still follow).
    assert ctrl.head_yaw == pytest.approx(head_before, abs=1e-9)


def test_a_stale_detection_never_moves_a_motor():
    ctrl = GazeController(now=0.0)
    first = ctrl.update(0.05, FaceSample(0.4, 0.0, 0.05))
    stale = ctrl.update(0.5, FaceSample(-0.9, 0.0, 0.2))  # 300 ms old
    assert stale is first
    assert ctrl.head_yaw == first.head_yaw


def test_a_stale_detection_with_no_history_releases_the_layer():
    ctrl = GazeController(now=0.0)
    assert ctrl.update(1.0, FaceSample(0.9, 0.0, 0.1)) is None


def test_loss_ladder_coasts_then_eases_home_then_looks_around_then_releases():
    ctrl = GazeController(now=0.0)
    last_seen = 0.0
    t = 0.0
    for _ in range(40):  # 2 s of a face at the left
        t += STEP
        ctrl.update(t, FaceSample(-0.5, 0.0, t))
        last_seen = t
    held = ctrl.update(last_seen + 0.5, None)  # coast: holds
    assert held.head_yaw == ctrl.head_yaw
    pose = (held.head_yaw, held.body_yaw)
    assert pose[0] != 0.0
    mid = ctrl.update(last_seen + 0.8 + 1.5, None)  # half way home
    assert 0.0 < abs(mid.head_yaw) < abs(pose[0])
    home = ctrl.update(last_seen + 0.8 + 3.0, None)
    assert home.head_yaw == pytest.approx(0.0, abs=1e-9)
    assert home.body_yaw == pytest.approx(0.0, abs=1e-9)
    # Six seconds after loss the one look-around begins, bounded by 35 degrees of body.
    peak = 0.0
    t2 = last_seen + g.LOOK_AROUND_AFTER_S
    for i in range(1, 200):
        o = ctrl.update(t2 + i * 0.05, None)
        if o is None:
            break
        peak = max(peak, abs(o.body_yaw))
    assert 0.0 < peak <= g.LOOK_AROUND_BODY_RAD + 1e-9
    assert o is None  # released after one period
    assert ctrl.update(t2 + 30.0, None) is None


def test_look_at_points_the_gaze_without_a_face():
    ctrl = GazeController(now=0.0)
    ctrl.look_at(1.0, head_yaw=0.8, body_yaw=0.4)
    out = ctrl.update(1.05, None)
    assert out.head_yaw == pytest.approx(0.8)
    assert out.body_yaw == pytest.approx(0.4)
