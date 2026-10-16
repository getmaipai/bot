"""TOUCH-01 glue: the loop reads the worker's antenna probe and reacts."""

from __future__ import annotations

import threading

from maipai_body.hal.seam import AntennaPositions
from maipai_body.presence.touch import AntennaTouchDetector
from tests.test_run_loop import _make_loop


def _loop(*, asleep: bool | None = None):
    loop, parts = _make_loop(touch_detector=AntennaTouchDetector())
    clock = {"t": 100.0}
    loop._touch_clock = lambda: clock["t"]
    woken: list[bool] = []
    if asleep is not None:
        loop._is_asleep = lambda: asleep
        loop._wake_from_sleep = lambda: woken.append(True)
    return loop, parts, clock, woken


def _push(loop, clock, *, driven_at=None, samples=6):
    commanded = AntennaPositions(left=0.0, right=0.0)
    present = AntennaPositions(left=0.8, right=0.0)
    loop._expression.antenna_probe = lambda: (commanded, present, driven_at)
    for _ in range(samples):
        loop._touch_tick(threading.Event())
        clock["t"] += 0.05


def test_a_push_on_an_idle_robot_is_acknowledged_once():
    loop, _parts, clock, _woken = _loop()
    _push(loop, clock)
    assert loop._expression.ambient == ["perk"]


def test_a_push_wakes_a_sleeping_robot():
    loop, _parts, clock, woken = _loop(asleep=True)
    _push(loop, clock)
    assert woken == [True]


def test_no_reaction_while_the_worker_is_driving_the_antennas():
    loop, _parts, clock, _woken = _loop()
    loop._expression.antenna_probe = lambda: (
        AntennaPositions(left=0.0, right=0.0),
        AntennaPositions(left=0.8, right=0.0),
        clock["t"],
    )
    for _ in range(6):
        loop._touch_tick(threading.Event())
        clock["t"] += 0.05
    assert getattr(loop._expression, "ambient", []) == []


def test_no_probe_means_nothing_happens():
    loop, _parts, clock, _woken = _loop()
    loop._expression.antenna_probe = lambda: None
    for _ in range(6):
        loop._touch_tick(threading.Event())
    assert getattr(loop._expression, "ambient", []) == []
