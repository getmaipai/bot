"""Releases a lost-body stop latch once the wireless StackChan answers again.

A person pressing the stop keeps the latch; only the latch set by a lost
body link may clear by itself, and only after the link has been seen back
for the settle window.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from maipai_body.robot import Robot

LOG = logging.getLogger("maipai_body.bodies.stackchan.estop_recovery")
_FAILURE_LOG_INTERVAL_S = 60.0


class EstopRecovery:
    """Watch a robot stop latch and clear it when the body is back."""

    def __init__(
        self,
        robot: Robot,
        device_connected: Callable[[], bool],
        *,
        clock: Callable[[], float] = time.monotonic,
        settle_s: float = 3.0,
    ) -> None:
        self._robot = robot
        self._device_connected = device_connected
        self._clock = clock
        self._settle_s = settle_s
        self._seen_since: float | None = None
        self._last_failure_log_at: float | None = None

    def tick(self) -> bool:
        """Check once; return True only when this call released the latch."""
        if not self._robot.estop_engaged:
            self._seen_since = None
            return False
        if self._robot.estop_cause != "body_lost":
            self._seen_since = None
            return False
        if not self._device_connected():
            self._seen_since = None
            return False
        now = self._clock()
        if self._seen_since is None:
            self._seen_since = now
            return False
        if now - self._seen_since < self._settle_s:
            return False
        try:
            self._robot.estop.release()
        except Exception:
            if (
                self._last_failure_log_at is None
                or now - self._last_failure_log_at >= _FAILURE_LOG_INTERVAL_S
            ):
                LOG.exception("could not release the lost-link stop latch")
                self._last_failure_log_at = now
            self._seen_since = now
            return False
        LOG.info("StackChan answered again; the stop caused by the lost link was released")
        return True

    def run(self, stop_event: threading.Event, *, every_s: float = 1.0) -> None:
        """Loop tick on a timer until the event is set; exceptions never escape."""
        while not stop_event.is_set():
            try:
                self.tick()
            except Exception:
                LOG.exception("StackChan stop recovery tick failed")
            stop_event.wait(every_s)


__all__ = ["EstopRecovery"]
