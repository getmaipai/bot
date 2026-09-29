"""Push the body's current robot.state frame to the paired hub."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import requests

logger = logging.getLogger("maipai_body.link.state")


class StateReporter:
    """Send state on changes and periodically refresh the hub's snapshot."""

    def __init__(
        self,
        hub_credentials: Callable[[], tuple[str, str]],
        stop_event: threading.Event,
        snapshot: Callable[[], dict[str, Any]],
        on_change: threading.Event,
        *,
        interval_s: float = 15.0,
        timeout: float = 5.0,
        session: requests.Session | None = None,
    ) -> None:
        self._hub_credentials = hub_credentials
        self._stop_event = stop_event
        self._snapshot = snapshot
        self._on_change = on_change
        self._interval_s = interval_s
        self._timeout = timeout
        self._session = session or requests.Session()

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._on_change.clear()
            try:
                cookie, base_url = self._hub_credentials()
                frame = self._snapshot()
                response = self._session.put(
                    f"{base_url}/api/devices/me/state",
                    json=frame,
                    headers={"Cookie": f"session={cookie}"},
                    timeout=self._timeout,
                )
                if not 200 <= response.status_code < 300:
                    logger.warning("robot state report returned HTTP %s", response.status_code)
            except Exception:
                logger.warning("robot state report failed", exc_info=True)
            if self._stop_event.is_set():
                return
            deadline = time.monotonic() + self._interval_s
            while not self._stop_event.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._on_change.wait(min(remaining, 0.25)):
                    break
