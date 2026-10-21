"""StackChan stays still while charging (owner request 2026-10-20).

While on USB power the robot must not wander: idle motion is switched off
automatically, and the same happens when night is active or the configured
``robot.idle.level`` is ``still``. On battery the configured level applies
again. A failing ``set_idle_motion`` is logged at most once a minute and
retried, so a failed write is never lost.
"""

from __future__ import annotations

import logging
import time

import pytest

from maipai_body.bodies.stackchan.power_idle import PowerIdle

LOGGER = "maipai_body.bodies.stackchan.power_idle"


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Motion:
    """Records the idle-motion writes; a flag makes the device call raise."""

    def __init__(self) -> None:
        self.writes: list[bool] = []
        self.fail = False

    def __call__(self, enabled: bool) -> None:
        if self.fail:
            raise RuntimeError("the idle-motion tool call is gone")
        self.writes.append(enabled)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == LOGGER]


def test_not_charging_and_calm_writes_true_once_because_the_unit_flag_is_unknown():
    motion = Motion()
    power = PowerIdle(motion, configured_level=lambda: "calm")
    power.on_battery_status(False)
    assert motion.writes == [True]  # the unit may boot with motion off: say so explicitly
    power.refresh()
    assert motion.writes == [True]


def test_plugging_in_writes_false_once_and_repeated_readings_write_nothing():
    motion = Motion()
    power = PowerIdle(motion)
    power.on_battery_status(True)
    assert motion.writes == [False]
    power.on_battery_status(True)
    assert motion.writes == [False]


def test_unplugging_writes_true_once():
    motion = Motion()
    power = PowerIdle(motion)
    power.on_battery_status(True)
    motion.writes.clear()
    power.on_battery_status(False)
    assert motion.writes == [True]
    power.on_battery_status(False)
    assert motion.writes == [True]


def test_unplugging_while_configured_level_is_still_writes_nothing():
    motion = Motion()
    level = {"value": "calm"}
    power = PowerIdle(motion, configured_level=lambda: level["value"])
    power.on_battery_status(True)
    motion.writes.clear()
    level["value"] = "still"
    power.on_battery_status(False)
    assert motion.writes == []


def test_unplugging_at_night_writes_nothing_and_refresh_after_night_writes_true():
    motion = Motion()
    night = {"value": False}
    power = PowerIdle(motion, night_active=lambda: night["value"])
    power.on_battery_status(True)
    motion.writes.clear()
    night["value"] = True
    power.on_battery_status(False)
    assert motion.writes == []
    night["value"] = False
    power.refresh()
    assert motion.writes == [True]


def test_level_still_on_battery_refresh_writes_false_then_calm_writes_true():
    motion = Motion()
    level = {"value": "calm"}
    power = PowerIdle(motion, configured_level=lambda: level["value"])
    power.on_battery_status(False)  # known to be on battery
    level["value"] = "still"
    power.refresh()
    assert motion.writes == [True, False]
    level["value"] = "calm"
    power.refresh()
    assert motion.writes == [True, False, True]


def test_failing_write_warns_at_most_once_a_minute_does_not_raise_and_retries(caplog):
    clock = FakeClock()
    motion = Motion()
    power = PowerIdle(motion, clock=clock)
    motion.fail = True
    with caplog.at_level("WARNING", logger=LOGGER):
        power.on_battery_status(True)
        clock.advance(30.0)
        power.on_battery_status(True)
        clock.advance(60.0)
        power.on_battery_status(True)
        motion.fail = False
        power.on_battery_status(True)
    assert len(_warnings(caplog)) == 2
    assert motion.writes == [False]


def test_still_is_true_while_charging_regardless_of_level():
    power = PowerIdle(lambda _enabled: None, configured_level=lambda: "lively")
    assert power.still is True  # unknown power is still
    power.on_battery_status(True)
    assert power.still is True
    power.on_battery_status(False)
    assert power.still is False


def test_charging_defaults_to_false_until_told():
    power = PowerIdle(lambda _enabled: None)
    assert power.charging is False
    power.on_battery_status(True)
    assert power.charging is True


def test_the_light_poller_tells_the_power_rule_and_a_failing_callback_never_stops_it():
    from maipai_body.bodies.stackchan.light_service import StackChanLightService
    from maipai_body.bodies.stackchan.light_wiring import LightPoller

    class _Indicator:
        def set_look(self, look):
            pass

        def off(self):
            pass

        def tick(self):
            pass

    seen: list[bool] = []

    def on_battery(charging: bool) -> None:
        seen.append(charging)
        if len(seen) == 1:
            raise RuntimeError("boom")

    poller = LightPoller(
        StackChanLightService(_Indicator()),
        link_phase=lambda: "connected",
        device_connected=lambda: True,
        battery=lambda: {"percent": 90, "charging": True},
        on_battery=on_battery,
    )
    poller.poll()
    assert seen == [True]


def test_unknown_power_is_still_until_the_unit_reports_it_is_on_battery():
    clock = FakeClock()
    motion = Motion()
    power = PowerIdle(motion, clock=clock)
    assert power.still is True
    power.tick()
    assert motion.writes == [False]  # idle motion is switched off before any reading
    power.tick()
    assert motion.writes == [False]  # and not written again
    power.on_battery_status(False)
    assert power.still is False
    assert motion.writes == [False, True]  # a positive on-battery reading frees it


def test_a_reading_older_than_three_minutes_is_unknown_again():
    clock = FakeClock()
    motion = Motion()
    power = PowerIdle(motion, clock=clock)
    power.on_battery_status(False)
    assert power.still is False
    clock.advance(179.0)
    assert power.still is False
    clock.advance(2.0)
    assert power.still is True
    power.tick()
    assert motion.writes[-1] is False


def test_a_failed_write_is_retried_after_five_seconds_not_every_tick():
    clock = FakeClock()
    motion = Motion()
    motion.fail = True
    attempts: list[bool] = []

    def counting(enabled: bool) -> None:
        attempts.append(enabled)
        motion(enabled)

    power = PowerIdle(counting, clock=clock)
    power.tick()
    power.tick()
    power.tick()
    assert len(attempts) == 1  # no hammering a unit that is not answering
    clock.advance(5.1)
    power.tick()
    assert len(attempts) == 2
    motion.fail = False
    clock.advance(5.1)
    power.tick()
    assert motion.writes == [False]


def test_the_idle_level_setting_is_read_and_still_turns_the_motion_off():
    clock = FakeClock()
    motion = Motion()
    level = {"value": "calm"}
    power = PowerIdle(motion, clock=clock, configured_level=lambda: level["value"])
    power.on_battery_status(False)
    assert power.still is False
    level["value"] = "still"
    power.refresh()
    assert power.still is True and motion.writes[-1] is False


def test_a_read_only_tool_is_asked_twice_but_a_motion_tool_is_not():
    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient

    calls: list[str] = []

    class _Server:
        def call_device_tool(self, name, arguments, timeout):
            calls.append(name)
            raise TimeoutError("slow")

    client = XiaozhiDeviceClient(_Server())
    for call in (client.get_battery_status, client.get_head_angles):
        try:
            call()
        except Exception:
            pass
    assert calls == ["self.battery.get_status"] * 2 + ["self.robot.get_head_angles"] * 2
    calls.clear()
    try:
        client.set_head_angles(0, 45, 150)
    except Exception:
        pass
    assert calls == ["self.robot.set_head_angles"]


def test_the_app_reads_the_idle_level_setting_and_feeds_the_power_rule():
    import inspect

    from maipai_body import app

    night = inspect.getsource(app._start_stackchan_night)
    assert 'values.get("robot.idle.level")' in night and "behavior.idle_level" in night
    serve = inspect.getsource(app._serve_stackchan_channels)
    assert "configured_level=lambda: behavior.idle_level" in serve
    assert "power.tick()" in serve


def test_a_reconnect_writes_the_idle_motion_flag_again():
    motion = Motion()
    power = PowerIdle(motion, configured_level=lambda: "calm")
    power.on_battery_status(False)
    assert motion.writes == [True]
    power.on_reconnect()  # the unit came back; its flag may have reset
    assert motion.writes == [True]  # marked unknown only; the tick writes it
    power.tick()
    assert motion.writes == [True, True]
    power.on_battery_status(True)
    power.on_reconnect()
    power.tick()
    assert motion.writes[-1] is False  # charging: it is told to stay still again


def test_the_head_gate_refuses_ambient_moves_when_still_but_never_a_response():
    from maipai_body.bodies.stackchan.head_gate import HeadMotionGate

    still = {"value": True}
    resting = {"value": False}
    now = [0.0]
    gate = HeadMotionGate(
        must_be_still=lambda: still["value"], resting=lambda: resting["value"], clock=lambda: now[0]
    )
    assert gate.allow("ambient:settle") is False
    assert gate.allow("turn:listening", response=True) is True
    still["value"] = False
    assert gate.allow("ambient:settle") is True
    resting["value"] = True
    assert gate.allow("ambient:attend") is False
    assert (gate.allowed, gate.denied) == (2, 2)


def test_every_head_decision_is_logged_with_its_source_once_per_interval(caplog):
    import logging

    from maipai_body.bodies.stackchan.head_gate import HeadMotionGate

    now = [0.0]
    gate = HeadMotionGate(must_be_still=lambda: True, clock=lambda: now[0], log_every_s=30.0)
    with caplog.at_level(logging.INFO, logger="maipai_body.bodies.stackchan.head_gate"):
        for _ in range(5):
            gate.allow("ambient:settle")
            now[0] += 1
        now[0] += 30
        gate.allow("ambient:settle")
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 2 and "refused: ambient:settle" in lines[0]


def test_the_ambient_head_moves_of_the_behavior_pass_through_the_gate():
    import inspect

    from maipai_body.app import StackChanBehavior

    source = inspect.getsource(StackChanBehavior.render_primitive)
    assert "self.head_gate.allow" in source


def test_a_hello_notifies_the_session_listeners_and_a_failing_one_is_isolated():
    from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer

    seen: list[str] = []
    server = XiaozhiServer(PairingStore(), robot=None)
    server.session_listeners.append(seen.append)
    server.session_listeners.insert(0, lambda device_id: (_ for _ in ()).throw(RuntimeError("x")))
    server._notify_session_listeners("device-1")  # listeners run on their own thread
    deadline = time.monotonic() + 2.0
    while not seen and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen == ["device-1"]
