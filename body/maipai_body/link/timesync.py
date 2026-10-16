"""ROBOT-TIME-01: the robot's clock comes from the hub.

The hub is the time authority on the link (dev.md section 7). Every redeem
response carries a ``Date`` header and the channel's ``time`` command carries
``hub_time``; both feed :meth:`ClockSync.observe`. A drift over
``DRIFT_THRESHOLD_S`` is corrected through the injected ``set_clock``; a
smaller drift changes nothing. ``synced`` is false until the first contact
since boot, and HLC stamping waits on it (:meth:`wait_synced`). No NTP
client: the robot has no better source than the hub it is paired with.

The ``Date`` header has one-second resolution, so a drift exactly at the
threshold is never corrected. The real setter (:func:`system_clock_setter`)
needs a privileged ``date`` call (the SDK's helper or a sudoers line the
installer writes); which one exists is UNVERIFIED until the arrival-day row,
and a refusal logs and leaves ``synced`` true (the hub's time is still known).
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

logger = logging.getLogger("maipai_body.link.timesync")

DRIFT_THRESHOLD_S = 1.0


def system_clock_setter(run: Callable[..., object] = subprocess.run) -> Callable[[float], None]:
    """Set the system clock through ``sudo -n date`` (UNVERIFIED on the unit)."""

    def set_clock(epoch_s: float) -> None:
        run(["sudo", "-n", "/bin/date", "-u", "-s", f"@{int(epoch_s)}"], check=True, timeout=5)

    return set_clock


class ClockSync:
    def __init__(
        self,
        set_clock: Callable[[float], None] | None = None,
        *,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._set_clock = set_clock
        self._wall_clock = wall_clock
        self._synced = threading.Event()
        self.corrections = 0
        self.last_drift_s: float | None = None

    @property
    def synced(self) -> bool:
        return self._synced.is_set()

    def wait_synced(self, timeout_s: float | None = None) -> bool:
        """HLC stamping waits here for the first sync after boot."""
        return self._synced.wait(timeout_s)

    def observe(self, hub_epoch_s: float) -> None:
        drift = hub_epoch_s - self._wall_clock()
        self.last_drift_s = drift
        if abs(drift) > DRIFT_THRESHOLD_S and self._set_clock is not None:
            try:
                self._set_clock(hub_epoch_s)
                self.corrections += 1
            except Exception:
                logger.warning("could not set the robot clock (drift %.1f s)", drift, exc_info=True)
        self._synced.set()

    def observe_http_date(self, header: str | None) -> None:
        if not header:
            return
        try:
            self.observe(parsedate_to_datetime(header).timestamp())
        except (TypeError, ValueError):
            logger.warning("unreadable Date header from the hub: %r", header)

    def observe_iso(self, hub_time: str) -> None:
        try:
            parsed = datetime.fromisoformat(hub_time.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("unreadable hub_time from the hub: %r", hub_time)
            return
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        self.observe(parsed.timestamp())
