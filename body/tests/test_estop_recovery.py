"""The lost-link stop latch clears by itself; the pressed one waits for a person."""

from __future__ import annotations

import math
import threading
import time

import pytest

from maipai_body.bodies.stackchan import StackChanRobotAdapter
from maipai_body.bodies.stackchan.estop_recovery import EstopRecovery
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.hal.errors import BodyLost
from maipai_body.hal.seam import HeadPose
from maipai_body.robot import Robot


def _latch_with_body_lost() -> tuple[FakeStackChanDeviceClient, Robot]:
    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    robot.lease.acquire("person", "estop-recovery")
    device.connected = False
    with pytest.raises(BodyLost):
        robot.head.goto(pose=HeadPose(pitch=math.radians(45)))
    return device, robot


def test_estop_cause_is_none_when_not_engaged():
    robot = StackChanRobotAdapter(FakeStackChanDeviceClient()).robot
    assert robot.estop_engaged is False
    assert robot.estop_cause is None


def test_estop_cause_tracks_the_latch_and_clears_on_release():
    robot = StackChanRobotAdapter(FakeStackChanDeviceClient()).robot
    robot.emergency_stop()
    assert robot.estop_cause == "user"
    robot.estop.release()
    assert robot.estop_engaged is False
    assert robot.estop_cause is None


def test_body_lost_during_leased_head_move_latches_with_cause_body_lost():
    _device, robot = _latch_with_body_lost()
    assert robot.estop_engaged is True
    assert robot.estop_cause == "body_lost"


def test_user_latch_is_never_downgraded_by_a_later_body_lost():
    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    robot.emergency_stop()
    assert robot.estop_cause == "user"
    device.connected = False
    with pytest.raises(BodyLost):
        robot.emergency_stop()
    assert robot.estop_engaged is True
    assert robot.estop_cause == "user"


def test_recovery_releases_body_lost_latch_after_settle_with_device_back():
    device, robot = _latch_with_body_lost()
    now = [0.0]
    recovery = EstopRecovery(robot, lambda: device.connected, clock=lambda: now[0])
    device.connected = True
    assert recovery.tick() is False
    now[0] = 2.99
    assert recovery.tick() is False
    assert robot.estop_engaged is True
    now[0] = 3.0
    assert recovery.tick() is True
    assert robot.estop_engaged is False
    assert robot.estop_cause is None
    robot.head.goto(pose=HeadPose(pitch=math.radians(45)))
    assert device.head_angles["pitch"] == 45


def test_recovery_does_not_release_before_settle():
    device, robot = _latch_with_body_lost()
    now = [0.0]
    recovery = EstopRecovery(robot, lambda: device.connected, clock=lambda: now[0])
    device.connected = True
    for _ in range(3):
        assert recovery.tick() is False
    assert robot.estop_engaged is True
    assert robot.estop_cause == "body_lost"
    now[0] = 3.0
    assert recovery.tick() is True


def test_recovery_resets_settle_while_the_device_is_disconnected():
    device, robot = _latch_with_body_lost()
    now = [0.0]
    recovery = EstopRecovery(robot, lambda: device.connected, clock=lambda: now[0])
    device.connected = True
    assert recovery.tick() is False
    now[0] = 2.0
    assert recovery.tick() is False
    device.connected = False
    now[0] = 10.0
    assert recovery.tick() is False
    assert robot.estop_engaged is True
    device.connected = True
    assert recovery.tick() is False
    now[0] = 13.0
    assert recovery.tick() is True
    assert robot.estop_engaged is False


def test_recovery_never_releases_a_user_latch():
    robot = StackChanRobotAdapter(FakeStackChanDeviceClient()).robot
    robot.emergency_stop()
    now = [0.0]
    recovery = EstopRecovery(robot, lambda: True, clock=lambda: now[0])
    for value in (0.0, 3.0, 60.0):
        now[0] = value
        assert recovery.tick() is False
    assert robot.estop_engaged is True
    assert robot.estop_cause == "user"


def test_failing_release_is_swallowed_and_retried_after_settle():
    device, robot = _latch_with_body_lost()
    now = [0.0]
    attempts = 0

    class FailingEstopDriver:
        def command(self, verb: str) -> object:
            nonlocal attempts
            attempts += 1
            raise RuntimeError("release refused")

    robot._drivers["estop"] = FailingEstopDriver()
    recovery = EstopRecovery(robot, lambda: device.connected, clock=lambda: now[0])
    device.connected = True
    for value in (0.0, 3.0, 6.0, 9.0):
        now[0] = value
        assert recovery.tick() is False
    assert attempts == 3
    assert robot.estop_engaged is True
    assert robot.estop_cause == "body_lost"
    now[0] = 12.0
    assert recovery.tick() is False
    assert attempts == 4


def test_release_failure_logs_at_most_once_per_minute(caplog):
    import logging

    caplog.set_level(logging.ERROR, logger="maipai_body.bodies.stackchan.estop_recovery")
    device, robot = _latch_with_body_lost()
    now = [0.0]

    class FailingEstopDriver:
        def command(self, verb: str) -> object:
            raise RuntimeError("release refused")

    robot._drivers["estop"] = FailingEstopDriver()
    recovery = EstopRecovery(robot, lambda: device.connected, clock=lambda: now[0])
    device.connected = True
    for value in (3.0, 6.0, 67.0, 70.0):
        now[0] = value
        assert recovery.tick() is False
    failures = [r for r in caplog.records if "could not release" in r.getMessage()]
    assert len(failures) == 2


def test_run_stops_when_the_event_is_set():
    _device, robot = _latch_with_body_lost()
    device = FakeStackChanDeviceClient()
    recovery = EstopRecovery(robot, lambda: device.connected, clock=time.monotonic)
    stop = threading.Event()
    thread = threading.Thread(target=recovery.run, args=(stop,), kwargs={"every_s": 0.01})
    thread.start()
    time.sleep(0.05)
    stop.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive()


def test_run_never_lets_tick_exceptions_escape():
    _device, robot = _latch_with_body_lost()

    def broken_check() -> bool:
        raise RuntimeError("state probe failed")

    recovery = EstopRecovery(robot, broken_check, clock=time.monotonic)
    stop = threading.Event()
    thread = threading.Thread(target=recovery.run, args=(stop,), kwargs={"every_s": 0.01})
    thread.start()
    time.sleep(0.05)
    stop.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
