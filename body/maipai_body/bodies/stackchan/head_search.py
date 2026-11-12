"""A short, quiet look around: a few head poses in turn, for one reason, with a cap and a back-off.

Owner requests 2026-11-12 ("natural, not annoying"; the 2026-10-20 "head still" rule no longer
holds the face search or the turn toward a speaker back, owner-approved the same day). Reasons:
"person": the picture suggests someone (it differs from the learned empty-room picture, or it
moves, or it is flat in a lit room: a body or an arm against the lens) but no face is in it, so
the head glances up a little first, then looks further up and over to each side, and stops the
moment a face is seen. "speaker": the same look right after the person spoke to the robot and no
face was in view. "dark": the picture has no detail and the light sensor sits at its floor, so
before the robot concludes the room is dark it looks left, right and a little up.

Every value that shapes the motion is here. This module keeps only the schedule (which pose is
due when, whether the look is over, when the same reason may run again after a failure); the
behavior in app.py asks the head gate for every move, never looks during a reply, at night or
while resting, stops at a face or a touch, and returns the head to its resting pose at the end.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

# How a look feels: slow, eased moves (the servo's slowest setting) and a person-like pause at
# each pose, so the whole look for a face takes about six seconds.
MOVE_SPEED = 100  # the servo's speed setting, 100 (slowest, smooth) to 150 (brisk)
TURN_SPEED = 130  # the one brisk move: turning toward someone who just spoke
MOVE_S = 1.0  # a move takes about this long at MOVE_SPEED
STEP_S = 1.6  # one pose is held this long in all (the move plus a pause of about half a second)
GLANCE_PITCH_DEG = 12.0  # the small first glance up, before any full sweep
LOOK_PITCH_DEG = 22.0  # the full look up (a face above the frame at desk distance)
PAN_DEG = 25.0  # how far to each side
DARK_PITCH_DEG = 15.0  # the small look up in a dark check
SPEAKER_PITCH_DEG = 15.0  # the glance up when someone speaks and no face is in view

# A failed look (no face found) is not repeated at once: the wait grows 1, 3, 10 minutes and
# resets when a face is found. "speaker" and "dark" have one fixed wait each.
PERSON_BACKOFF_S = (60.0, 180.0, 600.0)
SPEAKER_COOLDOWN_S = 15.0
DARK_COOLDOWN_S = 600.0


@dataclass(frozen=True)
class SearchStep:
    yaw_deg: float  # left is negative, as follow_pose has it
    pitch_deg: float  # degrees up from the resting (level) pitch


PERSON_STEPS = (
    SearchStep(0.0, GLANCE_PITCH_DEG),
    SearchStep(0.0, LOOK_PITCH_DEG),
    SearchStep(-PAN_DEG, LOOK_PITCH_DEG),
    SearchStep(PAN_DEG, LOOK_PITCH_DEG),
)
DARK_STEPS = (
    SearchStep(-PAN_DEG, 0.0),
    SearchStep(PAN_DEG, 0.0),
    SearchStep(0.0, DARK_PITCH_DEG),
)
STEPS = {"person": PERSON_STEPS, "speaker": PERSON_STEPS, "dark": DARK_STEPS}


class HeadSearch:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.reason: str | None = None
        self._steps: tuple[SearchStep, ...] = ()
        self._index = -1
        self._next_at = 0.0
        self.started_at: float | None = None
        self._last_done: dict[str, float] = {}
        self._failures = 0  # person looks that found nobody in a row

    @property
    def active(self) -> bool:
        return self.reason is not None

    def wait_s(self, reason: str) -> float:
        """How long after the last look of this reason the next may start."""
        if reason == "speaker":
            return SPEAKER_COOLDOWN_S
        if reason == "dark":
            return DARK_COOLDOWN_S
        if self._failures == 0:
            return 0.0
        return PERSON_BACKOFF_S[min(self._failures, len(PERSON_BACKOFF_S)) - 1]

    def may_start(self, reason: str, now: float | None = None) -> bool:
        """Not already looking, and this reason's wait is over."""
        current = self._clock() if now is None else now
        if self.active:
            return False
        last = self._last_done.get(reason)
        return last is None or current - last >= self.wait_s(reason)

    def start(self, reason: str, now: float | None = None) -> bool:
        current = self._clock() if now is None else now
        steps = STEPS.get(reason, ())
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

    def stop(self, now: float | None = None, *, found: bool = False) -> str | None:
        """End the look (done, a face found, or something more important); returns its reason.
        A person look that found nobody lengthens the wait before the next; a face resets it."""
        current = self._clock() if now is None else now
        reason = self.reason
        if reason is not None:
            self._last_done[reason] = current
            if reason in ("person", "speaker"):
                self._failures = 0 if found else self._failures + 1
        self.reason = None
        self._steps = ()
        self._index = -1
        self.started_at = None
        return reason


__all__ = [
    "DARK_STEPS",
    "MOVE_SPEED",
    "PERSON_BACKOFF_S",
    "PERSON_STEPS",
    "STEP_S",
    "TURN_SPEED",
    "HeadSearch",
    "SearchStep",
]
