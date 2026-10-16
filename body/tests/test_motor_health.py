"""MOTOR-RECOVER-01, the watchdog and the recovery ladder: cycle the mode, read the
servo errors, offer a per-motor reboot on the hub's word, restart the daemon, and
raise a Repair that names the step that helped."""

from __future__ import annotations

from maipai_body.bodies.reachy_mini.fake import ManualClock
from maipai_body.bodies.reachy_mini.motors import Commanded
from maipai_body.hal.seam import AntennaPositions, HeadPose
from maipai_body.presence.motor_health import (
    OFFER_TIMEOUT_S,
    STUCK_AFTER_S,
    MotorHealth,
    PresentPose,
)
from tests.motor_fakes import FakeMotorBus

TARGET = Commanded(
    pose=HeadPose(yaw=0.3),
    antennas=AntennaPositions(left=0.2, right=0.2),
    body_yaw=0.0,
    settle_until=0.0,
)


def _rig(**overrides):
    clock = ManualClock(10.0)
    bus = FakeMotorBus()
    commanded = {"value": TARGET}

    def present():
        c = commanded["value"]
        if bus.faulted:
            return PresentPose(pose=HeadPose(yaw=0.0), antennas=c.antennas, body_yaw=0.0)
        return PresentPose(pose=c.pose, antennas=c.antennas, body_yaw=c.body_yaw)

    offers: list[list[str]] = []
    repairs: list[dict] = []
    health = MotorHealth(
        bus,
        commanded=lambda: commanded["value"],
        present=present,
        clock=clock,
        on_offer=offers.append,
        on_repair=repairs.append,
        **overrides,
    )
    return health, bus, clock, offers, repairs, commanded


def _run(health, clock, seconds, *, held=False, step=0.5):
    for _ in range(int(seconds / step)):
        clock.advance(step)
        health.tick(held=held)


def test_a_healthy_body_does_nothing():
    health, bus, clock, offers, repairs, _ = _rig()
    _run(health, clock, 30)
    assert bus.calls == []
    assert health.status() == {"motors_latched": [], "motors_stuck": False}


def test_a_fake_that_ignores_enabled_after_a_fault_is_recovered_by_the_cycle():
    health, bus, clock, offers, repairs, _ = _rig()
    bus.plant_fault(cleared_by="cycle")
    _run(health, clock, STUCK_AFTER_S - 0.6)
    assert health.status()["motors_stuck"] is False, "not stuck before the window"
    assert "set_motor_mode:disabled" not in bus.calls
    _run(health, clock, 1.5)
    assert bus.calls.count("set_motor_mode:disabled") == 1
    assert bus.calls.index("set_motor_mode:disabled") < bus.calls.index("set_motor_mode:enabled")
    _run(health, clock, 1.0)
    assert health.status() == {"motors_latched": [], "motors_stuck": False}
    assert [r["helped"] for r in repairs] == ["cycle"]
    assert repairs[0]["resolved"] is True and repairs[0]["tried"] == ["cycle"]


def test_a_latched_servo_is_reported_and_reboot_waits_for_the_hubs_command():
    health, bus, clock, offers, repairs, _ = _rig()
    bus.plant_fault(cleared_by="reboot", latched=("head_1",))
    _run(health, clock, 6.0)
    assert health.status() == {"motors_latched": ["head_1"], "motors_stuck": True}
    assert offers == [["head_1"]], "offered once, through the hub's card"
    assert not any(c.startswith("reboot_motor") for c in bus.calls)
    assert "restart_daemon" not in bus.calls, "waits for the owner's answer first"
    assert health.confirm_reboot("head_1") is True
    assert bus.calls.count("reboot_motor:head_1") == 1
    _run(health, clock, 2.0)
    assert health.status() == {"motors_latched": [], "motors_stuck": False}
    assert repairs[-1]["helped"] == "reboot"


def test_reboot_is_never_run_while_a_person_may_be_touching_the_head():
    health, bus, clock, offers, repairs, _ = _rig()
    bus.plant_fault(cleared_by="reboot", latched=("head_1",))
    _run(health, clock, 6.0)
    assert health.confirm_reboot("head_1", person_touching=True) is False
    assert health.confirm_reboot("not_a_latched_servo") is False
    assert not any(c.startswith("reboot_motor") for c in bus.calls)


def test_an_unanswered_offer_falls_through_to_the_daemon_restart():
    health, bus, clock, offers, repairs, _ = _rig()
    bus.plant_fault(cleared_by="restart", latched=("head_1",))
    _run(health, clock, 6.0)
    assert "restart_daemon" not in bus.calls
    _run(health, clock, OFFER_TIMEOUT_S + 1.0)
    assert bus.calls.count("restart_daemon") == 1
    _run(health, clock, 2.0)
    assert repairs[-1]["helped"] == "daemon_restart"
    assert not any(c.startswith("reboot_motor") for c in bus.calls)


def test_no_latched_servo_goes_straight_to_the_daemon_restart():
    health, bus, clock, offers, repairs, _ = _rig()
    bus.plant_fault(cleared_by="restart")
    _run(health, clock, 8.0)
    assert offers == []
    assert bus.calls.count("restart_daemon") == 1
    assert repairs[-1]["helped"] == "daemon_restart"
    assert repairs[-1]["tried"] == ["cycle", "registers", "daemon_restart"]


def test_unreadable_registers_are_recorded_and_the_ladder_continues():
    health, bus, clock, offers, repairs, _ = _rig()
    bus.registers_readable = False
    bus.plant_fault(cleared_by="restart")
    _run(health, clock, 8.0)
    assert repairs[-1]["tried"] == ["cycle", "registers_unavailable", "daemon_restart"]
    assert repairs[-1]["helped"] == "daemon_restart"


def test_a_ladder_that_helps_nothing_raises_one_unresolved_repair():
    health, bus, clock, offers, repairs, _ = _rig()
    bus.plant_fault(cleared_by=None)
    _run(health, clock, 30.0)
    assert len(repairs) == 1
    assert repairs[0]["resolved"] is False and repairs[0]["helped"] is None
    assert repairs[0]["tried"] == ["cycle", "registers", "daemon_restart"]
    assert health.status()["motors_stuck"] is True
    assert bus.calls.count("restart_daemon") == 1, "the ladder runs once, it never loops"


def test_a_missing_sudoers_line_is_recorded_not_hidden():
    health, bus, clock, offers, repairs, _ = _rig()
    bus.restart_allowed = False
    bus.plant_fault(cleared_by="restart")
    _run(health, clock, 30.0)
    assert repairs[0]["tried"] == ["cycle", "registers", "daemon_restart_refused"]
    assert repairs[0]["resolved"] is False


def test_a_held_body_is_never_judged_stuck():
    health, bus, clock, offers, repairs, _ = _rig()
    bus.plant_fault(cleared_by="cycle")
    _run(health, clock, 20.0, held=True)
    assert bus.calls == []
    assert health.status()["motors_stuck"] is False


def test_a_goto_still_in_flight_is_not_a_stall():
    health, bus, clock, offers, repairs, commanded = _rig()
    commanded["value"] = Commanded(
        pose=HeadPose(yaw=0.3), antennas=None, body_yaw=None, settle_until=10.0 + 6.0
    )
    bus.plant_fault(cleared_by="cycle")
    _run(health, clock, 5.0)
    assert bus.calls == []


def test_a_brief_lag_that_catches_up_never_trips_the_watchdog():
    health, bus, clock, offers, repairs, _ = _rig()
    bus.plant_fault(cleared_by="cycle")
    _run(health, clock, 1.5)
    bus.faulted = False
    _run(health, clock, 10.0)
    assert bus.calls == []
