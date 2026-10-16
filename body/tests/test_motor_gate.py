"""MOTOR-RECOVER-01, the awake gate: no target during a wake or a sleep, for 2.2 s after a
wake, never a stream from the sleep pose, enabled read back before motion, no motion on a
charging bus, and a safe exit."""

from __future__ import annotations

import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient, ManualClock
from maipai_body.bodies.reachy_mini.motors import (
    BUS_VOLTAGE_REFUSE_V,
    WAKE_QUIET_S,
    MotorGate,
)
from maipai_body.hal.seam import AntennaPositions, HeadPose
from tests.motor_fakes import FakeMotorBus


def _gate(*, start_in_sleep_pose: bool = False):
    clock = ManualClock(100.0)
    client = FakeReachyMiniClient(clock=clock)
    bus = FakeMotorBus()
    gate = MotorGate(client, bus, clock=clock, start_in_sleep_pose=start_in_sleep_pose)
    return gate, client, bus, clock


def _kinds(client):
    return [c.kind for c in client.sent_commands]


def test_the_quiet_window_after_a_wake_is_2_2_seconds():
    assert WAKE_QUIET_S == 2.2


def test_targets_during_the_wake_move_are_dropped_and_counted():
    gate, client, bus, clock = _gate()
    gate.wake_up()
    assert "wake_up" in bus.calls
    for _ in range(3):
        gate.set_target(pose=HeadPose(yaw=0.1))
        clock.advance(0.5)
    gate.goto(pose=HeadPose(yaw=0.1))
    assert _kinds(client) == []
    assert gate.dropped_targets == 4
    assert gate.drop_reasons["waking"] == 4
    clock.advance(1.0)  # 2.5 s after the wake
    gate.set_target(pose=HeadPose(yaw=0.1))
    assert _kinds(client) == ["set_target"]


def test_a_sleep_drops_every_target_until_the_next_wake():
    gate, client, bus, clock = _gate()
    gate.goto_sleep()
    clock.advance(30.0)
    gate.set_target(pose=HeadPose(yaw=0.1))
    gate.goto(pose=HeadPose(yaw=0.1))
    assert _kinds(client) == []
    assert gate.drop_reasons["asleep"] == 2
    gate.wake_up()
    clock.advance(WAKE_QUIET_S + 0.1)
    gate.goto(pose=HeadPose(yaw=0.1))
    assert _kinds(client) == ["goto"]


def test_a_stream_from_the_sleep_pose_becomes_a_goto_to_neutral_first():
    gate, client, bus, clock = _gate(start_in_sleep_pose=True)
    gate.set_target(pose=HeadPose(yaw=0.3), antennas=AntennaPositions(left=0.4, right=0.4))
    assert _kinds(client) == ["goto"]
    first = client.sent_commands[0]
    assert first.pose == HeadPose() and first.body_yaw == 0.0
    assert first.antennas == AntennaPositions(left=0.0, right=0.0)
    # The stream does not fight the move while it runs...
    gate.set_target(pose=HeadPose(yaw=0.3))
    assert _kinds(client) == ["goto"]
    assert gate.drop_reasons["neutral_first"] >= 1
    # ...and flows once it has arrived.
    clock.advance(first.duration_s + 0.1)
    gate.set_target(pose=HeadPose(yaw=0.3))
    assert _kinds(client) == ["goto", "set_target"]


def test_enabled_is_asserted_and_read_back_before_motion():
    gate, client, bus, clock = _gate()
    bus.mode = "disabled"
    gate.set_target(pose=HeadPose(yaw=0.1))
    assert "set_motor_mode:enabled" in bus.calls
    assert bus.calls.index("set_motor_mode:enabled") < len(bus.calls)
    assert bus.mode == "enabled"
    assert _kinds(client) == ["set_target"]


def test_motion_is_refused_when_enabled_will_not_read_back():
    gate, client, bus, clock = _gate()
    bus.plant_fault(cleared_by="restart")
    bus.mode = "disabled"
    gate.set_target(pose=HeadPose(yaw=0.1))
    assert _kinds(client) == []
    assert gate.drop_reasons["not_enabled"] == 1


def test_a_bus_reading_7_2_volts_refuses_motion_with_a_logged_reason(caplog):
    gate, client, bus, clock = _gate()
    bus.voltage_v = 7.2
    assert BUS_VOLTAGE_REFUSE_V == 7.0
    with caplog.at_level("WARNING", logger="maipai_body.bodies.reachy_mini.motors"):
        gate.set_target(pose=HeadPose(yaw=0.1))
        gate.goto(pose=HeadPose(yaw=0.1))
    assert _kinds(client) == []
    assert gate.drop_reasons["charging"] == 2
    assert "7.2 V" in caplog.text and "7.0 V" in caplog.text
    bus.voltage_v = 6.4
    clock.advance(5.0)
    gate.set_target(pose=HeadPose(yaw=0.1))
    assert _kinds(client) == ["set_target"]


def test_an_unreadable_voltage_does_not_block_motion():
    gate, client, bus, clock = _gate()
    bus.voltage_v = None
    gate.set_target(pose=HeadPose(yaw=0.1))
    assert _kinds(client) == ["set_target"]


def test_hold_is_never_gated():
    gate, client, bus, clock = _gate()
    gate.goto_sleep()
    bus.voltage_v = 7.5
    gate.hold()
    assert _kinds(client) == ["hold"]


def test_other_calls_pass_straight_through():
    gate, client, bus, clock = _gate()
    gate.start_recording()
    assert gate.profile is client.profile


def test_safe_exit_enables_and_rests_over_a_distance_scaled_duration():
    gate, client, bus, clock = _gate()
    gate.goto(pose=HeadPose(yaw=0.1))
    gate.goto(pose=HeadPose(yaw=0.4))
    bus.mode = "disabled"
    gate.safe_exit()
    assert bus.mode == "enabled"
    near = client.sent_commands[-1]
    assert near.kind == "goto" and near.pose == HeadPose()
    clock.advance(10.0)
    gate.goto(pose=HeadPose(yaw=0.1), body_yaw=0.9)
    gate.safe_exit()
    far = client.sent_commands[-1]
    assert far.duration_s > near.duration_s
    assert "goto_sleep" not in bus.calls, "a plain stop never sleeps the robot"


def test_safe_exit_on_a_charging_bus_enables_but_does_not_move():
    gate, client, bus, clock = _gate()
    bus.voltage_v = 7.3
    bus.mode = "disabled"
    gate.safe_exit()
    assert bus.mode == "enabled"
    assert _kinds(client) == []


def test_safe_exit_leaves_a_sleeping_robot_asleep():
    gate, client, bus, clock = _gate()
    gate.goto_sleep()
    gate.safe_exit()
    assert _kinds(client) == []
    assert bus.calls.count("wake_up") == 0


@pytest.mark.parametrize("method", ["goto", "set_target"])
def test_an_out_of_envelope_target_still_raises_through_the_gate(method):
    from maipai_body.hal.errors import OutOfEnvelope

    gate, client, bus, clock = _gate()
    with pytest.raises(OutOfEnvelope):
        getattr(gate, method)(pose=HeadPose(yaw=9.0))
