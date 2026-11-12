"""A short, quiet look around: a few head poses in turn, for one reason, with a cap and a cooldown.

Two reasons exist (owner requests 2026-11-12). "person": the picture keeps changing but no face
is in it (an arm or a shoulder close to the lens, the usual case for a desktop robot), so the head
tilts up and pans to find the face, and stops the moment one is seen. "dark": the picture has no
detail and the light sensor sits at its floor, so before the robot concludes the room is dark it
looks left, right and a little up to make sure nothing is simply covering or facing it.

This module only keeps the schedule (which pose is due when, whether the search is over, when the
same reason may run again). The behavior in app.py asks the head gate before every move, never
runs a search during a turn, at night or while resting, and returns the head to centre at the end.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

STEP_S = 0.9  # one pose is held this long: two looks at the camera's pace
COOLDOWN_S = {"person": 60.0, "dark": 600.0}  # the same reason runs again only after this


@dataclass(frozen=True)
class SearchStep:
    yaw_deg: float  # left is negative, as follow_pose has it
    pitch_deg: float  # degrees up from the resting (level) pitch


# Up first (the face is above the frame when someone sits close), then over to each side.
PERSON_STEPS = (
    SearchStep(0.0, 20.0),
    SearchStep(-25.0, 20.0),
    SearchStep(25.0, 20.0),
    SearchStep(0.0, 10.0),
)
# Left, right and slightly up: a cover or a wall in front leaves detail somewhere, a dark room
# does not.
DARK_STEPS = (
    SearchStep(-25.0, 0.0),
    SearchStep(25.0, 0.0),
    SearchStep(0.0, 15.0),
)


class HeadSearch:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.reason: str | None = None
        self._steps: tuple[SearchStep, ...] = ()
        self._index = -1
        self._next_at = 0.0
        self.started_at: float | None = None
        self._last_done: dict[str, float] = {}

    @property
    def active(self) -> bool:
        return self.reason is not None

    def may_start(self, reason: str, now: float | None = None) -> bool:
        """Not already looking, and this reason's cooldown is over."""
        current = self._clock() if now is None else now
        if self.active:
            return False
        last = self._last_done.get(reason)
        return last is None or current - last >= COOLDOWN_S.get(reason, 60.0)

    def start(self, reason: str, steps: tuple[SearchStep, ...], now: float | None = None) -> bool:
        current = self._clock() if now is None else now
        if not steps or not self.may_start(reason, current):
            return False
        self.reason = reason
        self._steps = steps
        self._index = -1
        self._next_at = current  # the first pose is due at once
        self.started_at = current
        return True

    def due(self, now: float | None = None) -> SearchStep | None:
        """The next pose when its time has come, else None. After the last pose ``finished`` is
        True once its hold time is over."""
        current = self._clock() if now is None else now
        if not self.active or current + 1e-6 < self._next_at or self._index + 1 >= len(self._steps):
            return None
        self._index += 1
        assert self.started_at is not None
        self._next_at = self.started_at + (self._index + 1) * STEP_S  # from the start, not summed
        return self._steps[self._index]

    def finished(self, now: float | None = None) -> bool:
        current = self._clock() if now is None else now
        return (
            self.active and self._index + 1 >= len(self._steps) and current + 1e-6 >= self._next_at
        )

    def stop(self, now: float | None = None) -> str | None:
        """End the search (done, a face found, or something more important); returns its reason."""
        current = self._clock() if now is None else now
        reason = self.reason
        if reason is not None:
            self._last_done[reason] = current
        self.reason = None
        self._steps = ()
        self._index = -1
        self.started_at = None
        return reason


__all__ = ["DARK_STEPS", "PERSON_STEPS", "STEP_S", "HeadSearch", "SearchStep"]
