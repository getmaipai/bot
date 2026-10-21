"""The small, pure parts of idle face watching: the per-minute camera line and the greeting edge.

Nothing here sees a picture. It counts frames and bytes, and the moments a face was or was not in
view, so the log can say how heavy the unit's camera stream is and a greeting happens once when a
person comes back, not on every frame.
"""

from __future__ import annotations

from collections.abc import Callable

REPORT_EVERY_S = 60.0
GREET_AFTER_ABSENT_S = 600.0  # nobody in view this long, then seen again: a greeting
GREET_COOLDOWN_S = 1800.0  # and never twice within this


class CameraStats:
    """Counts for one log line a minute: what the unit sent, and what the host looked at."""

    def __init__(
        self,
        counters: Callable[[], tuple[int, int]],
        *,
        every_s: float = REPORT_EVERY_S,
    ) -> None:
        self._counters = counters
        self._every_s = every_s
        self._since: float | None = None
        self._frames0, self._bytes0 = 0, 0
        self._looked = 0
        self._with_face = 0
        self._look_ms = 0.0
        self._look_ms_max = 0.0

    def looked(self, elapsed_s: float, face: bool) -> None:
        """One frame was decoded and searched for a face (``elapsed_s`` is the whole look)."""
        self._looked += 1
        self._with_face += 1 if face else 0
        ms = elapsed_s * 1000.0
        self._look_ms += ms
        self._look_ms_max = max(self._look_ms_max, ms)

    def report(self, now: float) -> str | None:
        """The line for the minute that just ended, or None before it has ended."""
        frames, nbytes = self._counters()
        if self._since is None:
            self._since, self._frames0, self._bytes0 = now, frames, nbytes
            return None
        if now - self._since < self._every_s:
            return None
        minutes = (now - self._since) / 60.0
        line = (
            f"StackChan camera: {frames - self._frames0} frames and "
            f"{(nbytes - self._bytes0) / 1024:.0f} KB from the unit in {minutes:.1f} min; "
            f"looked at {self._looked} (a face in {self._with_face}), "
            f"mean {self._look_ms / self._looked if self._looked else 0.0:.1f} ms, "
            f"max {self._look_ms_max:.1f} ms"
        )
        self._since, self._frames0, self._bytes0 = now, frames, nbytes
        self._looked = self._with_face = 0
        self._look_ms = self._look_ms_max = 0.0
        return line


class GreetingPolicy:
    """True once when a face is seen after the room had been empty for a while."""

    def __init__(
        self,
        *,
        absent_s: float = GREET_AFTER_ABSENT_S,
        cooldown_s: float = GREET_COOLDOWN_S,
    ) -> None:
        self._absent_s = absent_s
        self._cooldown_s = cooldown_s
        self._last_seen: float | None = None
        self._last_greeted = float("-inf")

    def seen(self, now: float) -> bool:
        """A face is in view now; returns whether this is the moment to greet."""
        last, self._last_seen = self._last_seen, now
        absent_long_enough = last is None or now - last >= self._absent_s
        if not absent_long_enough or now - self._last_greeted < self._cooldown_s:
            return False
        self._last_greeted = now
        return True
