"""S-EXPR-04: the sleep state differs from muted, and the new cues end at neutral."""

from __future__ import annotations

import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient, ManualClock
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.expression.motion_worker import MotionLayer, MotionTarget, MotionWorker
from maipai_body.expression.reachy_mini_renderer import build_steps
from maipai_body.expression.suppression import SuppressionContext
from maipai_body.hal.seam import AntennaPositions, HeadPose
from maipai_body.presence.arbitration import ArbitrationState

AWAKE = ArbitrationState(expression_active=True)


def _last_antennas(client):
    for command in reversed(client.sent_commands):
        if command.antennas is not None:
            return command.antennas
    raise AssertionError("no antenna command reached the fake")


def _last_pose(client):
    for command in reversed(client.sent_commands):
        if command.pose is not None:
            return command.pose
    raise AssertionError("no pose command reached the fake")


def test_sleep_and_muted_differ_on_the_antenna_axis_by_at_least_0p3_rad():
    muted_client, sleep_client = FakeReachyMiniClient(), FakeReachyMiniClient()
    ExpressionEngine(muted_client, REACHY_MINI_PROFILE).set_muted(True, AWAKE)
    ExpressionEngine(sleep_client, REACHY_MINI_PROFILE).set_sleep(True, AWAKE)
    muted, asleep = _last_antennas(muted_client), _last_antennas(sleep_client)
    assert abs(muted.left - asleep.left) >= 0.3
    assert abs(muted.right - asleep.right) >= 0.3


def test_sleep_lowers_the_head_about_ten_degrees_and_waking_settles():
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    outcome = engine.set_sleep(True, AWAKE)
    assert outcome is not None and outcome.rendered_primitive == "sleep"
    assert _last_pose(client).pitch == pytest.approx(0.1745, abs=0.01)  # positive is down
    assert engine.set_sleep(True, AWAKE) is None  # no repeat on the same edge
    woke = engine.set_sleep(False, AWAKE)
    assert woke is not None and woke.rendered_primitive == "settle"
    assert _last_pose(client).pitch == pytest.approx(0.0, abs=0.02)


def test_shake_swings_ten_degrees_twice_and_returns_to_neutral():
    steps = build_steps("shake", REACHY_MINI_PROFILE)
    yaws = [step.pose.yaw for step in steps]
    assert yaws[:4] == pytest.approx([0.1745, -0.1745, 0.1745, -0.1745], abs=0.001)
    assert yaws[-1] == 0.0
    assert all(step.duration_s == pytest.approx(0.2) for step in steps)


def test_thinking_alternates_the_antennas_with_a_six_degree_roll():
    steps = build_steps("thinking", REACHY_MINI_PROFILE)
    assert steps[0].pose.roll == pytest.approx(0.1047, abs=0.002)
    assert steps[0].antennas.left == -steps[0].antennas.right != 0.0
    assert steps[1].antennas.left == -steps[0].antennas.left
    assert steps[-1].antennas.left == 0.0 and steps[-1].pose.roll == 0.0


def test_offer_twitches_both_antennas_twice_over_600_ms():
    steps = build_steps("offer", REACHY_MINI_PROFILE, doa_angle_rad=0.4)
    twitch = steps[:4]
    assert sum(step.duration_s for step in twitch) == pytest.approx(0.6)
    ups = [step.antennas.left > 0 and step.antennas.right > 0 for step in twitch]
    assert ups == [True, False, True, False]
    assert twitch[0].pose.yaw > 0.0  # a glance toward the person


def test_discrete_cues_stay_silent_while_muted():
    engine = ExpressionEngine(FakeReachyMiniClient(), REACHY_MINI_PROFILE)
    context = SuppressionContext(muted=True)
    for name in ("thinking", "offer", "shake"):
        assert engine.render_primitive(name, context).suppressed_reason == "muted"


def _drive(worker, clock, seconds):
    for _ in range(int(seconds / 0.02)):
        clock.advance(0.02)
        worker.tick(clock())


def _worker():
    clock = ManualClock(100.0)
    client = FakeReachyMiniClient()
    return MotionWorker(client, REACHY_MINI_PROFILE, clock=clock), clock, client


def _shake_sequence():
    steps = build_steps("shake", REACHY_MINI_PROFILE)
    return [
        (
            MotionTarget(
                pose=step.pose,
                antennas=AntennaPositions(left=0.0, right=0.0),
                owned_axes=frozenset({"head_pitch", "head_roll", "head_yaw"}),
            ),
            0.2,
        )
        for step in steps
    ]


def test_a_releasing_cue_hands_the_head_back_to_idle_when_it_ends():
    worker, clock, client = _worker()
    worker.set_layer(MotionLayer.IDLE, pose=HeadPose(yaw=0.2), duration_s=0.0)
    worker.submit_sequence(MotionLayer.EXPRESSION, _shake_sequence(), release_on_end=True)
    _drive(worker, clock, 4.0)
    assert worker.last_target.pose.yaw == pytest.approx(0.2, abs=0.01)


def test_a_non_releasing_cue_keeps_holding_its_last_pose():
    worker, clock, client = _worker()
    worker.set_layer(MotionLayer.IDLE, pose=HeadPose(yaw=0.2), duration_s=0.0)
    worker.submit_sequence(MotionLayer.EXPRESSION, _shake_sequence())
    _drive(worker, clock, 4.0)
    assert worker.last_target.pose.yaw == pytest.approx(0.0, abs=0.01)


def test_a_sleeping_robot_breathes_once_a_minute_and_waking_cancels_it():
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    assert engine.sleep_breathe(0.0) is False  # awake: nothing
    engine.set_sleep(True, AWAKE)
    assert engine.sleep_breathe(10.0) is False  # schedules the first breath
    assert engine.sleep_breathe(69.0) is False
    assert engine.sleep_breathe(70.0) is True
    assert engine.sleep_breathe(100.0) is False
    assert engine.sleep_breathe(130.0) is True
    engine.set_sleep(False, AWAKE)
    assert engine.sleep_breathe(400.0) is False
