"""The StackChan light wiring: poll the link, the device and the battery.

docs/dev/led-standard-2026-10-20.md ("The ring table"). ``LightPoller`` reads the
facts the ring may show (is the hub unreachable for 10 s, is the battery low)
and writes the changed ones into the ``StackChanLightService``; the battery is
read at most once per ``battery_every_s``. A failing or invalid read is
"unknown" and keeps the last good values (firmware patch 009 turns a failed
register read into "not charging" and 0 percent), and a change in the charging
or low state counts only after two reads in a row agree, so one bad read never
flaps anything. Charging itself is not a ring fact (the red light at the back
shows it); it only reaches the power rule through ``on_battery``.
``start_stackchan_light`` binds the service and a poller to the adapter's 12-pixel
ring as two daemon threads.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from maipai_body.bodies.stackchan.light_service import StackChanLightService
from maipai_body.bodies.stackchan.ring_indicator import StackChanRingIndicator
from maipai_body.indicator import looks

if TYPE_CHECKING:
    from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
    from maipai_body.link.offline import OfflineRungs

logger = logging.getLogger("maipai_body.bodies.stackchan.light_wiring")

LED_COUNT = 12
# The hub phases that mean "connected to the robot, but the hub is not
# reachable" (see maipai_body.link.state_machine.LinkPhase).
UNREACHABLE_PHASES = frozenset({"reconnecting", "sleeping"})
FAILURE_WARN_S = 60.0
# A battery state change counts after this many reads in a row agree on it.
CONFIRM_READS = 2


class _Confirmed:
    """A boolean that changes only after ``CONFIRM_READS`` equal reads in a row.

    The first read is taken as it is (there is nothing to flap from yet)."""

    def __init__(self) -> None:
        self.value: bool | None = None
        self._pending: bool | None = None
        self._count = 0

    def read(self, observed: bool) -> bool:
        if self.value is None:
            self.value = observed
            return observed
        if observed == self.value:
            self._pending, self._count = None, 0
            return self.value
        self._count = self._count + 1 if observed == self._pending else 1
        self._pending = observed
        if self._count >= CONFIRM_READS:
            self.value, self._pending, self._count = observed, None, 0
        return self.value


class LightPoller:
    """One pass of the light's pollers: the link, the device and the battery.

    ``poll()`` reads the facts and calls ``service.update`` once with only
    the fields that changed; the first poll also refreshes the service so
    the ring shows the current facts at once. The battery is read at most
    once per ``battery_every_s`` on the injected clock; a read that raises,
    returns an invalid payload (missing or non-int percent, non-bool
    charging) or looks like the firmware's failed-read zero (0 percent, not
    charging) keeps the previous values and warns at most once a minute.
    Offline shows after the link has been unreachable ``offline_after_s``.
    """

    def __init__(
        self,
        service: StackChanLightService,
        *,
        link_phase: Callable[[], str | None],
        device_connected: Callable[[], bool],
        battery: Callable[[], Mapping[str, object]],
        clock: Callable[[], float] = time.monotonic,
        battery_every_s: float = 60.0,
        low_percent: int = 15,
        on_battery: Callable[[bool], object] | None = None,
        offline_after_s: float = looks.ATTENTION_AFTER_S,
    ) -> None:
        self._service = service
        self._on_battery = on_battery
        self._link_phase = link_phase
        self._device_connected = device_connected
        self._battery = battery
        self._clock = clock
        self._battery_every_s = battery_every_s
        self._low_percent = low_percent
        self._offline_after_s = offline_after_s
        self._offline_since: float | None = None
        self._charging = _Confirmed()
        self._low = _Confirmed()
        self._last_battery_read: float | None = None
        self._last_failure_warn = float("-inf")
        self._first_poll = True

    def poll(self) -> None:
        connected = self._device_connected()
        now = self._clock()
        if connected and self._link_phase() in UNREACHABLE_PHASES:
            if self._offline_since is None:
                self._offline_since = now
            offline = now - self._offline_since >= self._offline_after_s
        else:
            self._offline_since = None
            offline = False
        if (
            self._last_battery_read is None
            or now - self._last_battery_read >= self._battery_every_s
        ):
            self._last_battery_read = now
            self._read_battery()
        facts = self._service.facts
        changes: dict[str, bool] = {}
        if facts.offline != offline:
            changes["offline"] = offline
        battery_low = bool(self._low.value)
        if facts.battery_low != battery_low:
            changes["battery_low"] = battery_low
        if changes:
            self._service.update(**changes)
        if self._first_poll:
            self._first_poll = False
            self._service.refresh()

    def run(self, stop_event: threading.Event, *, every_s: float = 1.0) -> None:
        """Poll, then wait ``every_s`` until ``stop_event`` is set; a
        failing poll is logged and the loop goes on."""
        while True:
            try:
                self.poll()
            except Exception:
                logger.warning("light poll failed", exc_info=True)
            if stop_event.wait(every_s):
                return

    def _read_battery(self) -> None:
        try:
            payload = self._battery()
        except Exception:
            self._warn_failure(exc_info=True)
            return
        percent = payload.get("percent")
        charging = payload.get("charging")
        if (
            isinstance(percent, int)
            and not isinstance(percent, bool)
            and isinstance(charging, bool)
            and not (percent == 0 and not charging)
        ):
            confirmed_charging = self._charging.read(charging)
            self._low.read(percent < self._low_percent and not charging)
            if self._on_battery is not None:
                try:
                    self._on_battery(confirmed_charging)
                except Exception:  # a power rule must never stop the light poll
                    logger.warning("power callback failed", exc_info=True)
            return
        self._warn_failure(exc_info=False)

    def _warn_failure(self, *, exc_info: bool) -> None:
        now = self._clock()
        if now - self._last_failure_warn >= FAILURE_WARN_S:
            logger.warning("battery read failed", exc_info=exc_info)
            self._last_failure_warn = now


def start_stackchan_light(
    voice_robot: StackChanRobotAdapter,
    link: OfflineRungs | None,
    stop_event: threading.Event,
    *,
    device_connected: Callable[[], bool] = lambda: True,
    on_battery: Callable[[bool], object] | None = None,
) -> StackChanLightService:
    """Build the ring indicator and service, start both loops, return the service.

    ``voice_robot`` is the StackChan adapter (its ``robot.leds.many`` is the
    ring's write, its ``client`` the battery reader); ``link`` is the offline
    rungs (its ``machine.phase`` the hub's phase) or None. The two loops run
    as daemon threads off ``stop_event``; the adapter is only built once a
    device is paired, so ``device_connected`` defaults to always true.
    """
    leds = voice_robot.robot.leds

    def write(rgb: tuple[int, int, int]) -> object:
        if not device_connected():
            return None  # no unit to light: a write would only fail and latch the stop again
        return leds.many([{"index": index, "rgb": list(rgb)} for index in range(LED_COUNT)])

    indicator = StackChanRingIndicator(write)
    service = StackChanLightService(indicator)

    def phase() -> str | None:
        if link is None:
            return None
        return link.machine.phase.value

    def battery() -> Mapping[str, object]:
        return voice_robot.client.get_battery_status()

    poller = LightPoller(
        service,
        link_phase=phase,
        device_connected=device_connected,
        battery=battery,
        on_battery=on_battery,
    )
    threading.Thread(
        target=service.run,
        args=(stop_event,),
        name="stackchan-light-service",
        daemon=True,
    ).start()
    threading.Thread(
        target=poller.run,
        args=(stop_event,),
        name="stackchan-light-poll",
        daemon=True,
    ).start()
    return service
