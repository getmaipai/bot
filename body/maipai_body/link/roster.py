"""FOLLOWUP-01 (bot half): fill the `PeopleDirectory` from the hub.

`GET /api/devices/me/people` returns a wholesale snapshot, `{as_of, people:
[{person_id, age_band, follow_up}]}`: a person missing from it is forgotten.
The poller refreshes at start, on a short interval and on `poke()` (a
reconnect). It never blocks the loop and never raises out of its thread: a
failed fetch keeps the last roster, and a roster that no fetch has confirmed
for `stale_s` is cleared so every speaker reads as unknown (the child
default, the safe direction). A rejected session (401 or 403) clears it at
once.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import requests

from maipai_body.speech.follow_up import PeopleDirectory

logger = logging.getLogger("maipai_body.link.roster")

DEFAULT_INTERVAL_S = 30.0
DEFAULT_STALE_S = 300.0
_BANDS = ("adult", "teen", "child")


class RosterPoller:
    def __init__(
        self,
        directory: PeopleDirectory,
        hub_credentials: Callable[[], tuple[str, str]],
        stop_event: threading.Event,
        *,
        interval_s: float = DEFAULT_INTERVAL_S,
        stale_s: float = DEFAULT_STALE_S,
        clock: Callable[[], float] = time.monotonic,
        session: requests.Session | None = None,
    ) -> None:
        self._directory = directory
        self._hub_credentials = hub_credentials
        self._stop_event = stop_event
        self._interval_s = interval_s
        self._stale_s = stale_s
        self._clock = clock
        self._session = session or requests.Session()
        self._last_ok: float | None = None
        self._wake = threading.Event()

    def poke(self) -> None:
        """Refresh now instead of waiting out the interval."""
        self._wake.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.refresh()
            except Exception:
                logger.warning("roster refresh failed; keeping the last roster", exc_info=True)
            self._wake.wait(self._interval_s)
            self._wake.clear()

    def refresh(self) -> bool:
        """One fetch. True when the directory now holds a fresh snapshot."""
        try:
            cookie, base_url = self._hub_credentials()
            response = self._session.get(
                f"{base_url}/api/devices/me/people",
                headers={"Cookie": f"session={cookie}"},
                timeout=5,
            )
        except Exception:
            logger.warning("roster fetch failed; keeping the last roster", exc_info=True)
            self._expire_if_stale()
            return False
        status = response.status_code
        if status in (401, 403):
            logger.info("hub rejected the roster fetch (%s); clearing the roster", status)
            self._directory.clear()
            self._last_ok = None
            return False
        if not 200 <= status < 300:
            logger.warning("roster fetch returned HTTP %s; keeping the last roster", status)
            self._expire_if_stale()
            return False
        try:
            roster = self._parse(response.json())
        except (KeyError, TypeError, ValueError):
            logger.warning("invalid roster response; keeping the last roster", exc_info=True)
            self._expire_if_stale()
            return False
        self._directory.replace_all(roster)
        self._last_ok = self._clock()
        return True

    @staticmethod
    def _parse(payload: object) -> dict:
        people = payload["people"]  # type: ignore[index]
        if not isinstance(people, list):
            raise TypeError("people is not a list")
        roster = {}
        for entry in people:
            person_id, band, follow_up = entry["person_id"], entry["age_band"], entry["follow_up"]
            if (
                not isinstance(person_id, str)
                or band not in _BANDS
                or not isinstance(follow_up, bool)
            ):
                raise ValueError(f"bad roster entry for {person_id!r}")
            roster[person_id] = (band, follow_up)
        return roster

    def _expire_if_stale(self) -> None:
        if self._last_ok is not None and self._clock() - self._last_ok > self._stale_s:
            logger.warning("roster is stale; every speaker reads as unknown")
            self._directory.clear()
            self._last_ok = None
