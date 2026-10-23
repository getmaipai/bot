"""The StackChan light service: facts in, one ring look out.

docs/dev/led-standard-2026-10-20.md wiring step 1. The service owns the
facts the ring may show (the funnel's shown state, the live and camera
cues, the connection and power rows), re-resolves one look from the one
table (``indicator/looks.py``, the only site of a colour or a level) on
every change and every ``refresh_s`` (so a night window edge is crossed
on time), and sends it to the ``StackChanRingIndicator``, which drives
its own style clock from a ``tick()`` about every 50 ms.

The live cue (green) and the camera cue (pink flash) are held for at
least ``looks.CUE_HOLD_S`` once raised, like the eyes' director: no
setting, night level or child level reaches them. The indicator never
raises: a failing write is logged and swallowed, so a light can never
break the voice or camera path.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from maipai_body.bodies.stackchan.ring_indicator import StackChanRingIndicator
from maipai_body.indicator import looks
from maipai_body.indicator.settings import IndicatorSettings
from maipai_body.presence.carry_reaction import PresenceEntry
from maipai_body.presence.funnel import FunnelState

logger = logging.getLogger("maipai_body.bodies.stackchan.light_service")


def _local_minute() -> int:
    now = datetime.now()
    return now.hour * 60 + now.minute


@dataclass(frozen=True)
class LightFacts:
    """Everything the ring decides from. All cues default to off and
    the funnel to idle, so a fresh service shows the idle look."""

    live: bool = False
    camera: bool = False
    alarm: bool = False
    alarm_on: bool = False
    held: bool = False
    muted: bool = False
    offer: bool = False
    fault: bool = False
    connecting: bool = False
    offline: bool = False
    pairing: bool = False
    charging: bool = False
    battery_low: bool = False
    updating: bool = False
    dancing: bool = False
    funnel: FunnelState = FunnelState.IDLE


class StackChanLightService:
    """Resolves the ring's one look from ``LightFacts`` and the look table.

    ``settings``, ``presence``, ``minute`` and ``clock`` are callables so
    the caller (or a test) can change the facts the service reads without
    a new service. ``update`` replaces named facts and re-resolves at
    once; ``refresh`` re-resolves the current facts, which the caller
    invokes at least every 60 s so a night window edge lands on time.
    """

    def __init__(
        self,
        indicator: StackChanRingIndicator,
        *,
        settings: Callable[[], IndicatorSettings] = IndicatorSettings,
        presence: Callable[[], Sequence[PresenceEntry] | None] = lambda: None,
        minute: Callable[[], int] = _local_minute,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._indicator = indicator
        self._suspended = False
        self._sleeping = False
        self._last_key: looks.LookKey | None = None
        self._settings = settings
        self._presence = presence
        self._minute = minute
        self._clock = clock
        self._facts = LightFacts()
        self._live_raised_at: float | None = None
        self._camera_raised_at: float | None = None

    @property
    def facts(self) -> LightFacts:
        return self._facts

    def update(self, **changes: bool | FunnelState) -> None:
        """Replace the named facts and re-resolve; an unknown name raises
        ``TypeError``."""
        self._facts = replace(self._facts, **changes)
        self._apply()

    def refresh(self) -> None:
        """Re-resolve the current facts (night edge, cue holds ending)."""
        self._release_due_cues()
        self._apply()

    @contextlib.contextmanager
    def suspended(self):
        """Hold the ring for a person-driven check (the self-test); the facts apply again after."""
        self._suspended = True
        try:
            yield self
        finally:
            self._suspended = False
            self._apply()

    def show(self, look) -> None:
        """Show one look (or dark) directly; for use inside ``suspended()`` only."""
        if look is None:
            self._indicator.off()
        else:
            self._indicator.set_look(look)

    def set_sleeping(self, sleeping: bool) -> None:
        """Darken the ring while asleep, then restore its currently resolved look."""
        if self._sleeping == sleeping:
            return
        self._sleeping = sleeping
        if sleeping:
            self._indicator.off()
        else:
            self._apply()

    def tick(self) -> None:
        """Advance the ring's style clock and let a finished cue hold end."""
        self._release_due_cues()
        self._indicator.tick()

    def cue_live(self, active: bool) -> None:
        """Raise or lower the live cue; once raised it holds at least
        ``looks.CUE_HOLD_S`` before the flag goes down."""
        now = self._clock()
        if active:
            if not self._facts.live:
                self._live_raised_at = now
                self.update(live=True)
            return
        if self._live_raised_at is not None and now - self._live_raised_at >= looks.CUE_HOLD_S:
            self._live_raised_at = None
            self.update(live=False)

    def cue_camera(self, active: bool) -> None:
        """Raise or lower the camera cue, with the same hold as ``cue_live``."""
        now = self._clock()
        if active:
            if not self._facts.camera:
                self._camera_raised_at = now
                self.update(camera=True)
            return
        if self._camera_raised_at is not None and now - self._camera_raised_at >= looks.CUE_HOLD_S:
            self._camera_raised_at = None
            self.update(camera=False)

    def run(
        self,
        stop_event: threading.Event,
        *,
        tick_s: float = 0.05,
        refresh_s: float = 60.0,
    ) -> None:
        """Tick the ring every ``tick_s`` and refresh every ``refresh_s``
        until ``stop_event`` is set, then turn the ring off."""
        last_refresh = self._clock()
        while not stop_event.wait(tick_s):
            self.tick()
            now = self._clock()
            if now - last_refresh >= refresh_s:
                self.refresh()
                last_refresh = now
        self._indicator.off()

    def _release_due_cues(self) -> None:
        if self._live_raised_at is not None:
            self.cue_live(False)
        if self._camera_raised_at is not None:
            self.cue_camera(False)

    def _apply(self) -> None:
        if self._sleeping:
            self._indicator.off()
            return
        if self._suspended:
            return
        facts = self._facts
        request = looks.LookRequest(
            funnel=facts.funnel,
            minute=self._minute(),
            settings=self._settings(),
            presence=self._presence(),
            live=facts.live,
            camera=facts.camera,
            alarm=facts.alarm,
            alarm_on=facts.alarm_on,
            held=facts.held,
            muted=facts.muted,
            offer=facts.offer,
            fault=facts.fault,
            connecting=facts.connecting,
            offline=facts.offline,
            pairing=facts.pairing,
            charging=facts.charging,
            battery_low=facts.battery_low,
            updating=facts.updating,
            dancing=facts.dancing,
        )
        look = looks.resolve(request)
        key = looks.resolve_key(request)
        if key != self._last_key:
            self._last_key = key
            logger.info("StackChan ring look: %s", key.value if key is not None else "dark")
        try:
            if look is None:
                self._indicator.off()
            else:
                self._indicator.set_look(look)
        except Exception:
            logger.warning("ring update failed", exc_info=True)
