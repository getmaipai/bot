"""Tell the hub which robot is connected and what it runs: firmware, address, memory, last seen.

The StackChan unit cannot call the hub itself, so the body reports for it. Facts come from three
places: the voice socket (the address and when it connected), the unit's diagnostic events (boot
reason, memory, firmware version) and its status tool (battery, signal class). Home may not have
the route yet; a 404 is read as "not there" and the body asks again in ten minutes."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import requests

logger = logging.getLogger("maipai_body.link.checkin")

CHECKIN_PATH = "/api/devices/me/checkin"
BOARD = "m5stack-stack-chan"
# The unit event kinds this record keeps the latest of, and the extra keys each contributes.
_KEPT: dict[str, tuple[str, ...]] = {
    "boot": ("reason", "crash_resets"),
    "heap_stats": ("int_free", "int_min", "psram_free"),
    "fw": ("version", "rssi"),
}


class UnitFacts:
    """The newest value of each fact the unit has reported since the body started."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._values: dict[str, Any] = {}
        self.changed = threading.Event()

    def observe(self, kind: str, extra: Mapping[str, Any] | None) -> None:
        keys = _KEPT.get(kind)
        if keys is None or not extra:
            return
        with self._lock:
            for key in keys:
                value = extra.get(key)
                if isinstance(value, (int, str)) and not isinstance(value, bool):
                    name = key if kind != "fw" else f"fw_{key}"
                    if kind == "boot":
                        name = f"boot_{key}"
                    if self._values.get(name) != value:
                        self._values[name] = value
                        if kind in {"boot", "fw"}:
                            self.changed.set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._values)


def build_payload(
    *,
    device_id: str | None,
    address: str | None,
    connected_since: float | None,
    facts: Mapping[str, Any],
    orientation: str | None = None,
    status: Mapping[str, Any] | None,
    bot_version: str | None,
    now: float,
) -> dict[str, Any]:
    """The check-in body. Every key is always present; unknown values are null."""
    battery = (status or {}).get("battery")
    battery = battery if isinstance(battery, Mapping) else {}
    network = (status or {}).get("network")
    network = network if isinstance(network, Mapping) else {}
    signal = network.get("signal")
    return {
        "device_id": device_id,
        "board": BOARD,
        "online": device_id is not None,
        "last_seen": datetime.fromtimestamp(now, UTC).isoformat(timespec="seconds"),
        "connected_since": (
            datetime.fromtimestamp(connected_since, UTC).isoformat(timespec="seconds")
            if connected_since is not None
            else None
        ),
        "ip": address,
        "firmware_version": facts.get("fw_version"),
        "bot_version": bot_version,
        "rssi": facts.get("fw_rssi"),
        "signal": signal if isinstance(signal, str) else None,
        "free_heap_internal": facts.get("int_free"),
        "free_heap_min": facts.get("int_min"),
        "psram_free": facts.get("psram_free"),
        "boot_reason": facts.get("boot_reason"),
        "crash_resets": facts.get("boot_crash_resets"),
        "battery_level": battery.get("level") if isinstance(battery.get("level"), int) else None,
        "orientation": orientation,
        "charging": battery.get("charging") if isinstance(battery.get("charging"), bool) else None,
    }


class RobotCheckin:
    """Report on connect, on a reboot or firmware change, and every ``interval_s`` seconds."""

    def __init__(
        self,
        hub_credentials: Callable[[], tuple[str, str]],
        stop_event: threading.Event,
        collect: Callable[[], dict[str, Any]],
        facts: UnitFacts,
        connected: threading.Event,
        *,
        interval_s: float = 60.0,
        timeout: float = 5.0,
        session: requests.Session | None = None,
    ) -> None:
        self._hub_credentials = hub_credentials
        self._stop_event = stop_event
        self._collect = collect
        self._facts = facts
        self._connected = connected
        self._interval_s = interval_s
        self._timeout = timeout
        self._session = session or requests.Session()
        self._last_online: bool | None = None

    def send_once(self) -> float:
        """One report; returns the seconds to wait before the next."""
        try:
            payload = self._collect()
            cookie, base_url = self._hub_credentials()
            response = self._session.put(
                f"{base_url}{CHECKIN_PATH}",
                json=payload,
                headers={"Cookie": f"session={cookie}"},
                timeout=self._timeout,
            )
        except Exception:
            logger.warning("robot check-in failed", exc_info=True)
            return self._interval_s
        if response.status_code == 404:
            logger.info("the hub has no robot check-in route yet; trying again in ten minutes")
            return 600.0
        if not 200 <= response.status_code < 300:
            logger.warning("robot check-in returned HTTP %s", response.status_code)
        return self._interval_s

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._facts.changed.clear()
            self._connected.clear()
            wait = self.send_once()
            deadline = time.monotonic() + wait
            while not self._stop_event.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._facts.changed.wait(min(remaining, 0.25)):
                    break
                if self._connected.is_set():
                    break
