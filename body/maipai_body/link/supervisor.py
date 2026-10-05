"""LINK-STATE-01: the thread that keeps the ladder moving.

``step()`` is one pass and takes no sleep, so the suite drives it on an
injected clock: tick the machine toward ``sleeping``, walk the addresses
when a walk is due (at once on a loss, then every ``reconnect_interval_s``,
and every ``sleeping_interval_s`` once asleep), let rung 0 render what the
phase owes the body, and fire a due local timer. ``run`` is the loop around
it for the app.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from maipai_body.link.commands import LocalTimers
from maipai_body.link.rung0 import Rung0Cues
from maipai_body.link.state_machine import LinkPhase, LinkStateMachine

logger = logging.getLogger("maipai_body.link.supervisor")


@dataclass(frozen=True)
class SupervisorSettings:
    # UNMEASURED defaults: the owner sets them after watching an outage on the unit.
    reconnect_interval_s: float = 30.0
    sleeping_interval_s: float = 300.0
    poll_s: float = 1.0


class LinkSupervisor:
    def __init__(
        self,
        *,
        machine: LinkStateMachine,
        reconnect: Callable[[], bool],
        clock: Callable[[], float] = time.monotonic,
        settings: SupervisorSettings = SupervisorSettings(),
        rung0: Rung0Cues | None = None,
        timers: LocalTimers | None = None,
        on_timer_due: Callable[[], None] | None = None,
    ) -> None:
        self._machine = machine
        self._reconnect = reconnect
        self._clock = clock
        self._settings = settings
        self._rung0 = rung0
        self._timers = timers
        self._on_timer_due = on_timer_due
        self._next_walk = clock()
        machine.subscribe(self._on_edge)

    def _on_edge(self, old: LinkPhase, new: LinkPhase) -> None:
        if new is LinkPhase.RECONNECTING:
            self._next_walk = self._clock()  # walk at once on a loss

    def step(self) -> None:
        phase = self._machine.tick()
        now = self._clock()
        if phase is not LinkPhase.CONNECTED and now >= self._next_walk:
            interval = (
                self._settings.sleeping_interval_s
                if phase is LinkPhase.SLEEPING
                else self._settings.reconnect_interval_s
            )
            self._next_walk = now + interval
            try:
                self._reconnect()
            except Exception as exc:
                logger.warning("address walk failed", exc_info=True)
                self._machine.redeem_failed(f"walk failed: {type(exc).__name__}")
        if self._rung0 is not None:
            try:
                self._rung0.tick()
            except Exception:
                logger.warning("rung 0 cue failed", exc_info=True)
        if self._timers is not None and self._timers.pop_due() and self._on_timer_due is not None:
            try:
                self._on_timer_due()
            except Exception:
                logger.warning("timer callback failed", exc_info=True)

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            self.step()
            stop_event.wait(self._settings.poll_s)
