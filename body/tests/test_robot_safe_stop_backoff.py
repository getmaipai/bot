"""A lost body runs the safe stop once, then at most every 30 s, not on every failing write."""

from __future__ import annotations

import pytest

import maipai_body.robot.core as core
from maipai_body.bodies.stackchan import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.hal.errors import BodyLost


def _lost_robot():
    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    device.connected = False
    runs = []
    original = robot._safe_stop

    def counting(**kwargs):
        runs.append(kwargs)
        return original(**kwargs)

    robot._safe_stop = counting
    return device, robot, runs


def _write(robot):
    with pytest.raises(BodyLost):
        robot.leds.many([{"index": i, "rgb": [1, 1, 1]} for i in range(12)])


def test_twenty_failing_writes_run_the_safe_stop_once(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(core.time, "monotonic", lambda: now[0])
    _device, robot, runs = _lost_robot()
    for _ in range(20):
        _write(robot)
        now[0] += 0.12
    assert len(runs) == 1
    assert robot.estop_cause == "body_lost"


def test_the_safe_stop_runs_again_after_the_backoff(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(core.time, "monotonic", lambda: now[0])
    _device, robot, runs = _lost_robot()
    _write(robot)
    now[0] += core.SAFE_STOP_BACKOFF_S + 1
    _write(robot)
    assert len(runs) == 2


def test_a_new_loss_after_the_stop_was_released_runs_the_safe_stop_at_once(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(core.time, "monotonic", lambda: now[0])
    device, robot, runs = _lost_robot()
    _write(robot)
    device.connected = True
    robot.estop.release()
    device.connected = False
    now[0] += 1.0
    _write(robot)
    assert len(runs) == 2


def test_the_ring_write_is_skipped_while_no_unit_is_connected():
    from types import SimpleNamespace

    from maipai_body.bodies.stackchan.light_wiring import start_stackchan_light

    calls = []
    connected = {"value": False}
    leds = SimpleNamespace(many=lambda colors: calls.append(colors))
    voice_robot = SimpleNamespace(
        robot=SimpleNamespace(leds=leds), client=SimpleNamespace(get_battery_status=lambda: {})
    )
    import threading

    stop = threading.Event()
    service = start_stackchan_light(
        voice_robot, None, stop, device_connected=lambda: connected["value"]
    )
    try:
        service.update(live=True)
        assert calls == []
        connected["value"] = True
        service.update(live=False)
        service.update(live=True)
        assert calls
    finally:
        stop.set()
