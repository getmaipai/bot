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
# Movement between two looks (owner finding 2026-11-12: at the desk the camera sees an arm or a
# shoulder, no face, so faces alone said "nobody"). The tiny gray thumbnails of two consecutive
# looks are compared cell by cell after the overall brightness change is taken out (auto exposure
# is not movement); the share of cells that changed by more than MOTION_CELL_DELTA is the movement.
# Measured 2026-11-12 on the unit: the empty lit office changed up to 6% of its cells by more than
# 12 between looks (sensor and JPEG noise) and 1% by more than 20; the owner still at his desk
# changed 7% to 31% by more than 20 in most pairs of looks, 57% when he moved.
MOTION_CELL_DELTA = 20.0  # of 255; noise between two looks at a still room stays under this
MOTION_FRACTION = 0.08  # at least 8 percent of the picture changed: something moved
MOTION_FRESH_S = 30.0  # "someone seems to be there" for this long after the last movement


def motion_fraction(previous: object, current: object) -> float:
    """The share of the picture that changed between two looks, 0.0 to 1.0 (0.0 when either is
    missing or their shapes differ). Pure arithmetic on two small gray arrays; nothing is kept."""
    import numpy as np

    if previous is None or current is None:
        return 0.0
    a = np.asarray(previous, dtype=np.float32)
    b = np.asarray(current, dtype=np.float32)
    if a.shape != b.shape or a.size == 0:
        return 0.0
    delta = b - a
    delta -= float(np.median(delta))  # a brightness step over the whole picture is not movement
    return float(np.mean(np.abs(delta) > MOTION_CELL_DELTA))


def moved(previous: object, current: object) -> bool:
    return motion_fraction(previous, current) >= MOTION_FRACTION


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
        self._luma: float | None = None  # light level of the newest frame: one number, no picture
        self._flat = False  # the newest frame had no detail, so its light level is unknown
        self._lux: float | None = None  # the unit's light sensor at the newest look
        self._moved = 0
        self._motion_max = 0.0

    def looked(
        self,
        elapsed_s: float,
        face: bool,
        *,
        luma: float | None = None,
        flat: bool = False,
        lux: float | None = None,
        motion: float | None = None,
    ) -> None:
        """One frame was decoded and searched for a face (``elapsed_s`` is the whole look).
        ``luma`` is its light level, ``flat`` says the picture had no detail to read one from, and
        ``motion`` is the share of the picture that changed since the look before."""
        self._looked += 1
        self._with_face += 1 if face else 0
        ms = elapsed_s * 1000.0
        self._look_ms += ms
        self._look_ms_max = max(self._look_ms_max, ms)
        self._lux = lux
        if flat:
            self._luma, self._flat = None, True
        elif luma is not None:
            self._luma, self._flat = luma, False
        if motion is not None:
            self._moved += 1 if motion >= MOTION_FRACTION else 0
            self._motion_max = max(self._motion_max, motion)

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
        if self._flat:
            from maipai_body.bodies.stackchan.vision_post import light_bucket

            verdict = light_bucket(None, self._lux, flat=True) or "cannot tell"
            line += (
                f"; light: the picture has no detail, sensor {self._lux} ({verdict}: "
                "dark room, or the lens is covered)"
            )
        elif self._luma is not None:
            from maipai_body.bodies.stackchan.vision_post import light_bucket

            line += f"; light {self._luma:.0f} of 255 ({light_bucket(self._luma)})"
        if self._looked:
            line += (
                f"; movement in {self._moved} looks "
                f"(at most {self._motion_max * 100:.0f}% of the picture)"
            )
        self._since, self._frames0, self._bytes0 = now, frames, nbytes
        self._looked = self._with_face = self._moved = 0
        self._look_ms = self._look_ms_max = self._motion_max = 0.0
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
