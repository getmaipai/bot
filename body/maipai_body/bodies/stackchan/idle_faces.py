"""Occasional, gentle expression changes while a StackChan is otherwise idle."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

MIN_WAIT_S = 30.0
MAX_WAIT_S = 90.0
MIN_GAP_S = 25.0
FACES = (("happy", 4), ("thinking", 3), ("sleepy", 2), ("surprised", 1), ("wink", 1))


class IdleFaces:
    """Choose a weighted idle face after a randomized quiet interval."""

    def __init__(
        self,
        show_face: Callable[[str], object],
        can_show: Callable[[], bool],
        *,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self._show_face = show_face
        self._can_show = can_show
        self._clock = clock
        self._rng = rng if rng is not None else random.Random()
        self._since = clock()
        self._wait = self._next_wait()
        self._last_look = float("-inf")
        self._last_face: str | None = None

    def tick(self, now: float) -> None:
        """Advance the scheduler; callers poll this about every two seconds."""
        if not self._can_show():
            self._since = now
            self._wait = self._next_wait()
            return
        if now - self._since < self._wait or now - self._last_look < MIN_GAP_S:
            return
        name = self._choose_face()
        self._show_face(name)
        self._last_face = name
        self._last_look = now
        self._since = now
        self._wait = self._next_wait()

    def _next_wait(self) -> float:
        return self._rng.uniform(MIN_WAIT_S, MAX_WAIT_S)

    def _choose_face(self) -> str:
        choices = [(name, weight) for name, weight in FACES if name != self._last_face]
        names, weights = zip(*choices)
        return self._rng.choices(names, weights=weights, k=1)[0]
