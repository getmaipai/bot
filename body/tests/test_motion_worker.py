"""S-EXPR-01R: layered targets go through one bounded 50 Hz writer."""

from __future__ import annotations

import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.motion_worker import (
    MotionLayer,
    MotionTarget,
    MotionWorker,
    entry_blend_seconds,
)
from maipai_body.hal.seam import AntennaPositions, HeadPose


def test_simultaneous_gaze_and_expression_stay_in_their_axis_budgets():
    client = FakeReachyMiniClient()
    worker = MotionWorker(client, REACHY_MINI_PROFILE, clock=lambda: 0.0)
    worker.set_layer(
        MotionLayer.GAZE,
        pose=HeadPose(yaw=0.8, pitch=0.4),
    )
    worker.set_layer(
        MotionLayer.EXPRESSION,
        pose=HeadPose(yaw=-0.8, pitch=-0.4, roll=0.5),
        antennas=AntennaPositions(left=0.7, right=-0.7),
    )

    for stamp in range(101):
        worker.tick(stamp * 0.02)

    target = client.sent_commands[-1]
    assert target.kind == "set_target"
    assert abs(target.pose.yaw) <= 0.7 * 0.8 + 0.3 * 0.8
    assert abs(target.pose.pitch) <= 0.7 * 0.4 + 0.3 * 0.4
    assert abs(target.pose.roll) <= 0.5
    assert target.antennas is None or target.antennas.left <= 0.7
    assert target.antennas is None or target.antennas.right >= -0.7


def test_tilt_during_gaze_blends_without_exceeding_the_profile_or_rate_caps():
    client = FakeReachyMiniClient()
    worker = MotionWorker(client, REACHY_MINI_PROFILE, clock=lambda: 0.0)
    worker.set_layer(MotionLayer.GAZE, pose=HeadPose(yaw=0.9))
    for stamp in range(26):
        worker.tick(stamp * 0.02)
    worker.set_layer(MotionLayer.EXPRESSION, pose=HeadPose(roll=0.4, yaw=-0.4))

    for stamp in range(1, 26):
        worker.tick(stamp * 0.02)

    commands = [c for c in client.sent_commands if c.kind == "set_target"]
    assert len(commands) >= 2
    assert max(abs(b.pose.yaw - a.pose.yaw) / 0.02 for a, b in zip(commands, commands[1:])) <= 1.0
    assert (
        max(abs(b.pose.roll - a.pose.roll) / 0.02 for a, b in zip(commands, commands[1:]))
        <= 0.200001
    )


def test_stop_bypasses_a_slow_motion_and_holds_within_one_worker_tick():
    client = FakeReachyMiniClient()
    worker = MotionWorker(client, REACHY_MINI_PROFILE, clock=lambda: 0.0)
    worker.set_layer(MotionLayer.EXPRESSION, pose=HeadPose(pitch=0.3), duration_s=2.0)
    worker.tick(0.0)

    worker.stop()

    assert client.sent_commands[-1].kind == "hold"


def test_dropped_cue_counter_increments_when_a_stale_target_is_rejected():
    worker = MotionWorker(FakeReachyMiniClient(), REACHY_MINI_PROFILE)

    worker.drop_stale_target()

    assert worker.dropped_cues == 1


def test_speech_sway_is_zero_below_the_hysteresis_gate():
    client = FakeReachyMiniClient()
    worker = MotionWorker(client, REACHY_MINI_PROFILE, clock=lambda: 0.0)
    worker.set_speech_rms(0.0)

    worker.tick(0.0)

    target = worker.last_target
    assert target.pose.pitch == pytest.approx(0.0)
    assert target.antennas.left == pytest.approx(0.0)
    assert target.antennas.right == pytest.approx(0.0)


def test_speech_sway_uses_the_ledger_energy_and_relaxes_to_zero_in_silence():
    worker = MotionWorker(FakeReachyMiniClient(), REACHY_MINI_PROFILE, clock=lambda: 0.0)
    worker.set_speech_rms(1.0)
    for stamp in range(101):
        worker.tick(stamp * 0.02)
    assert worker.last_target.pose.pitch > 0.0
    assert worker.last_target.antennas.left > 0.0

    worker.set_speech_rms(0.0)
    for stamp in range(101, 202):
        worker.tick(stamp * 0.02)
    assert worker.last_target.pose.pitch == pytest.approx(0.0, abs=1e-4)
    assert worker.last_target.antennas.left == pytest.approx(0.0, abs=1e-4)


def test_entry_blend_uses_distance_and_caps_its_duration():
    assert entry_blend_seconds(MotionTarget(), MotionTarget(pose=HeadPose(yaw=1.0))) == 1.5
    assert (
        entry_blend_seconds(
            MotionTarget(), MotionTarget(antennas=AntennaPositions(left=0.001, right=0.0))
        )
        == 0.0
    )
