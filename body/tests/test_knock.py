"""KNOCK-01: a double knock wakes the robot from sleep. Scripted IMU at 50 Hz."""

from __future__ import annotations

import threading

from maipai_body.bodies.reachy_mini.fake import rest_reading
from maipai_body.hal.seam import ImuReading
from maipai_body.presence.knock import KnockDetector
from tests.test_motion_state import shaken
from tests.test_run_loop import _make_loop

DT = 0.02


def spike(amplitude: float = 4.0) -> ImuReading:
    return ImuReading(
        accelerometer=(0.0, 0.0, 9.81 + amplitude),
        gyroscope=(0.0, 0.0, 0.0),
        quaternion=(1.0, 0.0, 0.0, 0.0),
        temperature_c=30.0,
    )


class Feed:
    def __init__(self, detector: KnockDetector | None = None) -> None:
        self.detector = detector or KnockDetector()
        self.now = 10.0
        self.fired = 0

    def step(self, reading: ImuReading, *, suppressed: bool = False) -> None:
        if self.detector.update(reading, self.now, suppressed=suppressed):
            self.fired += 1
        self.now += DT

    def quiet(self, seconds: float) -> None:
        for _ in range(round(seconds / DT)):
            self.step(rest_reading())

    def knock(self) -> None:
        self.step(spike())
        self.step(spike(2.0))
        self.step(rest_reading())


def test_a_double_knock_fires_exactly_once():
    feed = Feed()
    feed.quiet(0.5)
    feed.knock()
    feed.quiet(0.4)
    feed.knock()
    feed.quiet(2.0)
    assert feed.fired == 1


def test_a_single_knock_never_fires():
    feed = Feed()
    feed.knock()
    feed.quiet(3.0)
    assert feed.fired == 0


def test_two_knocks_too_far_apart_never_fire():
    feed = Feed()
    feed.knock()
    feed.quiet(1.5)
    feed.knock()
    feed.quiet(1.0)
    assert feed.fired == 0


def test_ring_down_is_one_knock_not_two():
    feed = Feed()
    feed.knock()
    feed.quiet(0.08)
    feed.knock()  # closer than the minimum spacing
    feed.quiet(1.5)
    assert feed.fired == 0


def test_a_scripted_carry_never_reads_as_a_knock():
    feed = Feed()
    feed.quiet(0.5)
    for step in range(120):  # 2.4 s of hand motion
        feed.step(shaken(step))
        if step % 25 == 24:
            feed.quiet(0.06)  # brief lulls between swings
    feed.quiet(3.0)
    assert feed.fired == 0


def test_suppression_clears_a_pending_knock():
    feed = Feed()
    feed.knock()
    feed.quiet(0.2)
    feed.step(rest_reading(), suppressed=True)
    feed.quiet(0.4)
    feed.knock()
    feed.quiet(1.0)
    assert feed.fired == 0


def test_a_missing_reading_changes_nothing():
    assert KnockDetector().update(None, 1.0) is False


# -- the run loop: wake from sleep and the status line --------------------------------------


def _knock_loop(asleep: bool):
    loop, parts = _make_loop()
    woken = []
    loop._is_asleep = lambda: asleep
    loop._wake_from_sleep = lambda: woken.append(True)
    clock = {"t": 100.0}
    loop._motion_clock = lambda: clock["t"]
    return loop, parts, woken, clock


def _double_knock(loop, parts, clock) -> None:
    sequence = [rest_reading()] * 5
    for _ in range(2):
        sequence += [spike(), spike(2.0)] + [rest_reading()] * 15
    sequence += [rest_reading()] * 5
    for reading in sequence:
        parts["client"].read = lambda reading=reading: reading
        loop._knock_tick(threading.Event())
        clock["t"] += DT


def test_a_double_knock_wakes_a_sleeping_robot_once():
    loop, parts, woken, clock = _knock_loop(asleep=True)
    _double_knock(loop, parts, clock)
    assert woken == [True]


def test_a_double_knock_on_an_awake_robot_does_nothing():
    loop, parts, woken, clock = _knock_loop(asleep=False)
    _double_knock(loop, parts, clock)
    assert woken == []


def test_a_held_robot_never_wakes_from_a_knock():
    loop, parts, woken, clock = _knock_loop(asleep=True)
    loop._motion._holding = True
    _double_knock(loop, parts, clock)
    assert woken == []


def test_the_knock_wake_asks_the_status_line():
    from tests.test_link_ladder_run_loop import _rungs

    offline, _clock, _volume, speaker = _rungs(recognizer=False)
    offline.machine.link_lost("unreachable: ConnectTimeout")
    loop, parts = _make_loop(offline=offline)
    loop._is_asleep = lambda: True
    woken = []
    loop._wake_from_sleep = lambda: woken.append(True)
    clock = {"t": 100.0}
    loop._motion_clock = lambda: clock["t"]
    _double_knock(loop, parts, clock)
    assert woken == [True]
    assert len(speaker.said) == 1


def test_the_app_wires_the_knock_to_the_ladders_sleeping_phase() -> None:
    from maipai_body.app import _knock_hooks
    from maipai_body.link.offline import OfflineRungs
    from maipai_body.link.state_machine import LinkStateMachine

    assert _knock_hooks(None) == (None, None)
    clock = [0.0]
    machine = LinkStateMachine(clock=lambda: clock[0], sleep_after_s=10.0)
    tries: list[int] = []
    offline = OfflineRungs(machine=machine, retry_link=lambda: tries.append(1) or False)
    is_asleep, wake = _knock_hooks(offline)
    assert is_asleep is not None and wake is not None
    assert not is_asleep()
    machine.link_lost("down")
    clock[0] = 11.0
    machine.tick()
    assert is_asleep()
    wake()
    assert tries == [1]
