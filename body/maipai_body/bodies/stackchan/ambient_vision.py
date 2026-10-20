"""BOT-SC-VISION-01 (host half): silent ambient vision keeps a text note, never the picture.

Privacy rule: no frame, thumbnail or pixel log is kept. A silent capture is
described into one short text note and the frame bytes are dropped in the
same call; only the note is handed to memory. The whole feature is opt-in
behind the ``robot.ambient_vision`` setting (default off), so a disabled
policy never approves a capture of any kind.

``AmbientVisionPolicy`` is pure and clock-injected, in the style of
``presence.sleep_auto.SleepAutoPolicy``: it sees numbers and flags, never
frames. Approvals are counted by the policy itself, so the hourly cap and
the gap between captures hold across both the ambient rule and the
on-demand "let me take a look" path.
"""

from __future__ import annotations

from collections.abc import Callable

NOTE_MAX_CHARS = 280
HOUR_S = 3600.0


class AmbientVisionPolicy:
    """Decides when a silent ambient capture is approved.

    A capture is approved only when the setting is on, the funnel has been
    idle for at least ``idle_after_s``, no turn is active, quiet hours are
    not active, no child is present, at least ``min_gap_s`` passed since the
    last approval, and fewer than ``max_per_hour`` approvals fall inside the
    last sliding 3600 s window."""

    def __init__(
        self,
        *,
        enabled: Callable[[], bool] = lambda: False,
        idle_after_s: float = 60.0,
        min_gap_s: float = 120.0,
        max_per_hour: int = 20,
    ) -> None:
        self.enabled = enabled
        self.idle_after_s = idle_after_s
        self.min_gap_s = min_gap_s
        self.max_per_hour = max_per_hour
        self._approved_at: list[float] = []

    def _recent(self, now: float) -> list[float]:
        self._approved_at = [approved for approved in self._approved_at if now - approved < HOUR_S]
        return self._approved_at

    def _at_cap(self, now: float) -> bool:
        return len(self._recent(now)) >= self.max_per_hour

    def should_capture(
        self,
        now: float,
        *,
        funnel_idle_s: float,
        turn_active: bool,
        quiet_hours_active: bool = False,
        child_present: bool = False,
    ) -> bool:
        """One funnel tick. Records an approval when it returns True."""
        if not self.enabled():
            return False
        if funnel_idle_s < self.idle_after_s:
            return False
        if turn_active or quiet_hours_active or child_present:
            return False
        if self._at_cap(now):
            return False
        recent = self._recent(now)
        if recent and now - recent[-1] < self.min_gap_s:
            return False
        self._approved_at.append(now)
        return True

    def capture_on_demand_allowed(self, now: float, *, turn_active: bool) -> bool:
        """ "Let me take a look": enabled and under the hourly cap is enough.

        The idle gate and the gap are ignored because the user asked, and a
        turn being active never blocks a request. Counts toward the cap."""
        del turn_active
        if not self.enabled():
            return False
        if self._at_cap(now):
            return False
        self._approved_at.append(now)
        return True


class AmbientVisionWorker:
    """One silent capture: describe the frame, keep the note, drop the frame.

    The camera is only a ``command("frame", silent=True)`` provider. No file
    is written, the bytes are never logged, and no attribute keeps a
    reference to the frame, so it is collectable as soon as the note exists."""

    def __init__(
        self,
        camera: object,
        describe: Callable[[bytes], str],
        remember: Callable[[str], None],
    ) -> None:
        self.camera = camera
        self.describe = describe
        self.remember = remember

    def run_once(self) -> str | None:
        frame = self.camera.command("frame", silent=True)
        if frame is None:
            return None
        try:
            note = self.describe(frame)
        finally:
            del frame
        if not isinstance(note, str) or not note.strip():
            return None
        kept = note.strip()[:NOTE_MAX_CHARS]
        self.remember(kept)
        return kept


__all__ = ["AmbientVisionPolicy", "AmbientVisionWorker", "NOTE_MAX_CHARS"]
