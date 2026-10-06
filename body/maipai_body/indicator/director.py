"""EYES-02: the director.

It subscribes to the presence funnel's ``FunnelView`` (the shown state, the
mute, held and alarm facts) and to ``LiveCaptureTap``'s ``CaptureFacts``, and
to nothing else: no turn client, no playback, no face tracking (an AST test
holds that line). Each change re-resolves one look from ``looks.py`` and
sends it only if it differs from what the eyes already show.

A capture cue is held for at least ``CUE_HOLD_S`` once raised. The alarm
blinks at ``ALARM_PERIOD_S``. A timer, or ``tick()`` in tests, lands both.
The indicator never raises ``BodyLost``; a device that fails anyway is
logged and never breaks the funnel's own threads.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from datetime import datetime

from maipai_body.hal.seam import Indicator, Look
from maipai_body.indicator import looks
from maipai_body.indicator.live import CaptureFacts
from maipai_body.indicator.settings import IndicatorSettings
from maipai_body.presence.carry_reaction import PresenceEntry
from maipai_body.presence.funnel import FunnelState, FunnelView

logger = logging.getLogger("maipai_body.indicator.director")

# Night is re-checked at least this often, so a window edge is crossed on time.
_RECHECK_S = 60.0


def _local_minute() -> int:
    now = datetime.now()
    return now.hour * 60 + now.minute


class _Hold:
    """A cue that, once raised, stays up at least ``CUE_HOLD_S``."""

    def __init__(self) -> None:
        self._active = False
        self._since = 0.0
        self._until = 0.0

    def set(self, active: bool, now: float) -> None:
        if active and not self._active:
            self._since = now
        if self._active and not active:
            self._until = max(self._until, now, self._since + looks.CUE_HOLD_S)
        self._active = active

    def touch(self, now: float) -> None:
        """An instant of activity, such as one frame read."""
        self._until = max(self._until, now + looks.CUE_HOLD_S)

    def on(self, now: float) -> bool:
        return self._active or now < self._until

    def due_in(self, now: float) -> float | None:
        if self._active or now >= self._until:
            return None
        return self._until - now


class EyesDirector:
    def __init__(
        self,
        indicator: Indicator,
        *,
        settings: Callable[[], IndicatorSettings] = IndicatorSettings,
        presence: Callable[[], Sequence[PresenceEntry] | None] = lambda: None,
        clock: Callable[[], float] = time.monotonic,
        local_minutes: Callable[[], int] = _local_minute,
        auto_timers: bool = True,
    ) -> None:
        self._indicator = indicator
        self._settings = settings
        self._presence = presence
        self._clock = clock
        self._local_minutes = local_minutes
        self._auto_timers = auto_timers
        self._lock = threading.RLock()
        self._view = FunnelView(shown=FunnelState.IDLE)
        self._live = _Hold()
        self._camera = _Hold()
        self._alarm_since: float | None = None
        self._applied: Look | None = None
        self._applied_known = False
        self._timer: threading.Timer | None = None
        self._closed = False
        self._last_read: float | None = None

    # -- inputs ---------------------------------------------------------

    def on_view(self, view: FunnelView) -> None:
        with self._lock:
            self._view = view
        self._apply()

    def on_capture(self, facts: CaptureFacts) -> None:
        now = self._clock()
        with self._lock:
            self._live.set(facts.mic_live, now)
            self._camera.set(facts.camera_tracking, now)
            if facts.camera_read_at is not None and facts.camera_read_at != self._last_read:
                self._last_read = facts.camera_read_at
                self._camera.touch(now)
        self._apply()

    def tick(self) -> None:
        """Re-resolve now (hold ends, alarm phase, night edge)."""
        self._apply()

    refresh = tick

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        try:
            self._indicator.off()
        except Exception:
            logger.warning("eyes off failed", exc_info=True)

    # -- output ---------------------------------------------------------

    def _alarm_on(self, now: float) -> bool:
        if self._alarm_since is None:
            return True
        half = looks.ALARM_PERIOD_S / 2
        return int((now - self._alarm_since) / half) % 2 == 0

    def _apply(self) -> None:
        with self._lock:
            if self._closed:
                return
            now = self._clock()
            view = self._view
            if view.alarm and self._alarm_since is None:
                self._alarm_since = now
            elif not view.alarm:
                self._alarm_since = None
            request = looks.LookRequest(
                funnel=view.shown,
                minute=self._local_minutes(),
                settings=self._settings(),
                presence=self._presence(),
                live=self._live.on(now),
                camera=self._camera.on(now),
                alarm=view.alarm,
                alarm_on=self._alarm_on(now),
                held=view.held,
                muted=view.muted,
            )
            look = looks.resolve(request)
            if not self._applied_known or look != self._applied:
                self._send(look)
                self._applied, self._applied_known = look, True
            self._arm_timer(now)

    def _send(self, look: Look | None) -> None:
        try:
            if look is None:
                self._indicator.off()
            else:
                self._indicator.set_look(look)
        except Exception:
            logger.warning("eyes update failed", exc_info=True)

    def _arm_timer(self, now: float) -> None:
        if not self._auto_timers:
            return
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        waits = [_RECHECK_S]
        for hold in (self._live, self._camera):
            due = hold.due_in(now)
            if due is not None:
                waits.append(due)
        if self._alarm_since is not None:
            half = looks.ALARM_PERIOD_S / 2
            elapsed = now - self._alarm_since
            waits.append(half - (elapsed % half))
        timer = threading.Timer(max(min(waits), 0.001), self._apply)
        timer.daemon = True
        self._timer = timer
        timer.start()
