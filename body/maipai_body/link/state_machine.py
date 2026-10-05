"""LINK-STATE-01: the connected, reconnecting, sleeping machine.

One small machine, no threads and no I/O of its own: the funnel
(``run_loop.py``), ``LinkLifecycle`` and the supervisor tell it what
happened (``link_lost``, ``redeem_failed``, ``redeemed``) and ``tick()``
moves it to ``sleeping`` once the outage has lasted ``sleep_after_s`` on
the injected clock. Its phase values are exactly the ``robot.state.activity``
values spec-v0.1.73 added (``reconnecting``, ``sleeping``) plus ``connected``,
which the funnel reports as its own ``idle``, ``listening`` and so on.

It also holds the real values rung 2's status text is built from (last
contact, attempts, the address being tried, which path answered, the last
error). Nothing here is invented: every field is set by a call above.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger("maipai_body.link.state_machine")

# UNMEASURED: LINK-STATE-01 says "a setting, default to be measured". This
# is a placeholder the owner replaces once an outage has been observed on
# the unit; nothing was measured to choose 30.
DEFAULT_SLEEP_AFTER_MINUTES = 30.0


class LinkPhase(StrEnum):
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    SLEEPING = "sleeping"


# The two values spec-v0.1.73 added to ``robot.state.activity``.
LADDER_ACTIVITIES = frozenset({LinkPhase.RECONNECTING.value, LinkPhase.SLEEPING.value})


@dataclass(frozen=True)
class LadderSnapshot:
    """A copy of the machine's values, safe to read across threads."""

    phase: LinkPhase
    since: float  # injected-clock time the phase was entered
    attempts: int  # address-walk attempts since this outage began
    current_address: str | None  # the address being tried, or last tried
    answered_path: str | None  # which path last answered: "lan" or "tailnet"
    last_connected_wall: float | None  # wall-clock time of the last redeem
    last_error: str | None


Listener = Callable[[LinkPhase, LinkPhase], None]


class LinkStateMachine:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleep_after_s: float = DEFAULT_SLEEP_AFTER_MINUTES * 60.0,
    ) -> None:
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleep_after_s = sleep_after_s
        self._lock = threading.Lock()
        self._listeners: list[Listener] = []
        self._phase = LinkPhase.CONNECTED
        self._since = clock()
        self._attempts = 0
        self._current_address: str | None = None
        self._answered_path: str | None = None
        self._last_connected_wall: float | None = None
        self._last_error: str | None = None

    @property
    def phase(self) -> LinkPhase:
        with self._lock:
            return self._phase

    @property
    def sleep_after_s(self) -> float:
        return self._sleep_after_s

    def snapshot(self) -> LadderSnapshot:
        with self._lock:
            return LadderSnapshot(
                phase=self._phase,
                since=self._since,
                attempts=self._attempts,
                current_address=self._current_address,
                answered_path=self._answered_path,
                last_connected_wall=self._last_connected_wall,
                last_error=self._last_error,
            )

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def _move(self, new: LinkPhase) -> tuple[LinkPhase, LinkPhase] | None:
        """Called under the lock. Returns the edge to announce, if any."""
        old = self._phase
        if old is new:
            return None
        self._phase = new
        self._since = self._clock()
        return old, new

    def _announce(self, edge: tuple[LinkPhase, LinkPhase] | None) -> None:
        if edge is None:
            return
        logger.info("link: %s -> %s", edge[0], edge[1])
        for listener in list(self._listeners):
            try:
                listener(*edge)
            except Exception:
                logger.warning("link state listener failed", exc_info=True)

    def link_lost(self, reason: str) -> None:
        """The funnel lost the hub mid-turn."""
        self._lost(reason)

    def redeem_failed(self, error: str) -> None:
        """A re-redeem (or a walk of every address) failed."""
        self._lost(error)

    def _lost(self, error: str) -> None:
        with self._lock:
            self._last_error = error
            edge = None
            if self._phase is LinkPhase.CONNECTED:
                edge = self._move(LinkPhase.RECONNECTING)
                self._attempts = 0
        self._announce(edge)

    def booted_without_contact(self, reason: str) -> None:
        """A body with a stored pairing powered on and the hub has not
        answered yet. The machine starts ``connected`` only because it has
        to start somewhere; with no redeem on record that claim is false, so
        this is a ``link_lost`` unless a redeem already happened (the
        hub-link thread can win the race; checked under the same lock)."""
        with self._lock:
            if self._last_connected_wall is not None:
                return
            self._last_error = reason
            edge = None
            if self._phase is LinkPhase.CONNECTED:
                edge = self._move(LinkPhase.RECONNECTING)
                self._attempts = 0
        self._announce(edge)

    def attempt(self, address: str) -> None:
        """The address walk is about to try ``address``."""
        with self._lock:
            self._attempts += 1
            self._current_address = address

    def redeemed(self, path: str, address: str | None = None) -> None:
        """A redeem succeeded, over ``path`` (``lan`` or ``tailnet``)."""
        with self._lock:
            self._answered_path = path
            if address is not None:
                self._current_address = address
            self._last_connected_wall = self._wall_clock()
            self._last_error = None
            edge = self._move(LinkPhase.CONNECTED)
        self._announce(edge)

    def tick(self) -> LinkPhase:
        """Move to ``sleeping`` once the outage has lasted long enough."""
        with self._lock:
            edge = None
            if (
                self._phase is LinkPhase.RECONNECTING
                and self._clock() - self._since >= self._sleep_after_s
            ):
                edge = self._move(LinkPhase.SLEEPING)
            phase = self._phase
        self._announce(edge)
        return phase
