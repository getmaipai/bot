"""StackChan stays still while charging (owner request 2026-10-20).

While on USB power the robot must not wander: idle motion is switched off
automatically, and the same happens when night is active or the configured
``robot.idle.level`` is ``still``. On battery the configured level applies
again. A failing ``set_idle_motion`` is logged at most once a minute and
retried, so a failed write is never lost.
"""

from __future__ import annotations

import logging

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


def test_not_charging_and_calm_writes_nothing_at_first():
    motion = Motion()
    power = PowerIdle(motion, configured_level=lambda: "calm")
    power.on_battery_status(False)
    assert motion.writes == []
    power.refresh()
    assert motion.writes == []


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
    level["value"] = "still"
    power.refresh()
    assert motion.writes == [False]
    level["value"] = "calm"
    power.refresh()
    assert motion.writes == [False, True]


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
    assert power.still is False
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
