"""LINK-STATE-01 rung 0: body-only cues, no speech, no new axis.

Everything here is an existing RM-02 primitive rendered through the
expression engine: ``settle`` and ``breathe`` when the link drops, the
``muted`` primitive's pose as the antenna away pose after a while (and at
once when sleeping), and ``perk`` then ``settle`` as the stir on reconnect.
Tracking is switched off after a configured time (and while sleeping) by
the run loop asking :meth:`Rung0Cues.tracking_allowed`.

``breathe`` is rendered once per outage: the continuous idle loop is
EXPR-04, which is not built. Nothing renders while a turn owns the head
(``may_drive``); the cue waits and renders on the next tick.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from maipai_body.link.state_machine import LinkPhase, LinkStateMachine

logger = logging.getLogger("maipai_body.link.rung0")

RECONNECT_CLIP = "line.reconnect"
# The `muted` primitive's pose is antennas folded away with the head level.
# Used here as the "away" pose; the mute state itself is untouched (the
# engine's `set_muted` edge is not involved).
AWAY_PRIMITIVE = "muted"


@dataclass(frozen=True)
class Rung0Settings:
    # UNMEASURED defaults: owner's call once an outage has been watched on the unit.
    away_after_s: float = 120.0
    tracking_off_after_s: float = 300.0


class Rung0Cues:
    def __init__(
        self,
        *,
        render: Callable[[str], bool],
        machine: LinkStateMachine,
        clock: Callable[[], float],
        settings: Rung0Settings = Rung0Settings(),
        may_drive: Callable[[], bool] = lambda: True,
        speaker=None,
        on_reconnect_spoken: Callable[[], None] | None = None,
    ) -> None:
        self._render = render
        self._machine = machine
        self._clock = clock
        self._settings = settings
        self._may_drive = may_drive
        self._speaker = speaker
        self._on_reconnect_spoken = on_reconnect_spoken
        self._lock = threading.Lock()
        self._stage = "none"  # none, settled, away
        self._stir_pending = False
        machine.subscribe(self._on_edge)

    def _on_edge(self, old: LinkPhase, new: LinkPhase) -> None:
        with self._lock:
            if new is LinkPhase.RECONNECTING:
                self._stage = "none"
                self._stir_pending = False
            elif new is LinkPhase.CONNECTED:
                self._stir_pending = True

    def tracking_allowed(self) -> bool:
        snap = self._machine.snapshot()
        if snap.phase is LinkPhase.CONNECTED:
            return True
        if snap.phase is LinkPhase.SLEEPING:
            return False
        return self._clock() - snap.since < self._settings.tracking_off_after_s

    def tick(self) -> None:
        """Render whatever the current phase owes the body, if it is free."""
        snap = self._machine.snapshot()
        with self._lock:
            stage, stir = self._stage, self._stir_pending
        if snap.phase is LinkPhase.CONNECTED:
            if stir and self._may_drive():
                with self._lock:
                    self._stir_pending = False
                self._stir()
            return
        if not self._may_drive():
            return
        if snap.phase is LinkPhase.RECONNECTING:
            if stage == "none":
                self._render("settle")
                self._render("breathe")
                self._set_stage("settled")
            elif stage == "settled":
                if self._clock() - snap.since >= self._settings.away_after_s:
                    self._render(AWAY_PRIMITIVE)
                    self._set_stage("away")
        elif stage != "away":
            self._render(AWAY_PRIMITIVE)
            self._set_stage("away")

    def _set_stage(self, stage: str) -> None:
        with self._lock:
            self._stage = stage

    def _stir(self) -> None:
        self._render("perk")
        self._render("settle")
        speaker = self._speaker
        if speaker is None or not speaker.can_say([RECONNECT_CLIP]):
            return
        try:
            spoke = speaker.say([RECONNECT_CLIP])
        except Exception:
            logger.warning("the reconnect clip could not be spoken", exc_info=True)
            return
        if spoke and self._on_reconnect_spoken is not None:
            self._on_reconnect_spoken()
