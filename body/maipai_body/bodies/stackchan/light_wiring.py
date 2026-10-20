"""The StackChan light wiring: poll the link, the device and the battery.

docs/dev/led-standard-2026-10-20.md wiring step 2. ``LightPoller`` reads the
facts the ring may show (is the robot not at the hub yet, is the hub
unreachable, is the battery charging or low) and writes the changed ones
into the ``StackChanLightService``; the battery is read at most once per
``battery_every_s`` and a failing or invalid read keeps the last good
values. ``start_stackchan_light`` binds the service and a poller to the
adapter's 12-pixel ring as two daemon threads.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from maipai_body.bodies.stackchan.light_service import StackChanLightService
from maipai_body.bodies.stackchan.ring_indicator import StackChanRingIndicator

if TYPE_CHECKING:
    from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
    from maipai_body.link.offline import OfflineRungs

logger = logging.getLogger("maipai_body.bodies.stackchan.light_wiring")

LED_COUNT = 12
# The hub phases that mean "connected to the robot, but the hub is not
# reachable" (see maipai_body.link.state_machine.LinkPhase).
UNREACHABLE_PHASES = frozenset({"reconnecting", "sleeping"})
FAILURE_WARN_S = 60.0


class LightPoller:
    """One pass of the light's pollers: the link, the device and the battery.

    ``poll()`` reads the facts and calls ``service.update`` once with only
    the fields that changed; the first poll also refreshes the service so
    the ring shows the current facts at once. The battery is read at most
    once per ``battery_every_s`` on the injected clock; a read that raises
    or returns an invalid payload (missing or non-int percent, non-bool
    charging) keeps the previous values and warns at most once a minute.
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
    ) -> None:
        self._service = service
        self._link_phase = link_phase
        self._device_connected = device_connected
        self._battery = battery
        self._clock = clock
        self._battery_every_s = battery_every_s
        self._low_percent = low_percent
        self._charging = False
        self._battery_low = False
        self._last_battery_read: float | None = None
        self._last_failure_warn = float("-inf")
        self._first_poll = True

    def poll(self) -> None:
        connected = self._device_connected()
        connecting = not connected
        offline = connected and self._link_phase() in UNREACHABLE_PHASES
        now = self._clock()
        if (
            self._last_battery_read is None
            or now - self._last_battery_read >= self._battery_every_s
        ):
            self._last_battery_read = now
            self._read_battery()
        facts = self._service.facts
        changes: dict[str, bool] = {}
        if facts.connecting != connecting:
            changes["connecting"] = connecting
        if facts.offline != offline:
            changes["offline"] = offline
        if facts.charging != self._charging:
            changes["charging"] = self._charging
        if facts.battery_low != self._battery_low:
            changes["battery_low"] = self._battery_low
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
        ):
            self._charging = charging
            self._battery_low = percent < self._low_percent and not charging
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
