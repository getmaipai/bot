"""One gate for every head movement the robot starts on its own (owner request 2026-10-20).

The unit kept moving because several sources could move the head (the idle settle, face following,
dance, look-at-speaker, expression gestures) and each decided for itself. ``HeadMotionGate`` is the
single answer to "may the head move now?": ambient sources are refused while the robot must be
still (power unknown, charging, night, ``robot.idle.level`` still, resting). A move that answers a
person during a turn is a response, not wandering, and always passes. Every decision is logged at
INFO, once per source and decision every ``log_every_s`` so the log names who moved the head.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

logger = logging.getLogger("maipai_body.bodies.stackchan.head_gate")


class HeadMotionGate:
    def __init__(
        self,
        *,
        must_be_still: Callable[[], bool],
        resting: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.monotonic,
        log_every_s: float = 30.0,
    ) -> None:
        self._must_be_still = must_be_still
        self._resting = resting
        self._clock = clock
        self._log_every_s = log_every_s
        self._last_logged: dict[tuple[str, bool], float] = {}
        self.allowed = 0
        self.denied = 0

    def allow(self, source: str, *, response: bool = False) -> bool:
        """Whether ``source`` may move the head now. ``response`` marks a move during a turn."""
        if response:
            verdict, reason = True, "answering a person"
        elif self._must_be_still():
            verdict, reason = False, "must be still (power unknown or charging, night, or level)"
        elif self._resting():
            verdict, reason = False, "resting"
        else:
            verdict, reason = True, "free to move"
        if verdict:
            self.allowed += 1
        else:
            self.denied += 1
        self._log(source, verdict, reason)
        return verdict

    def _log(self, source: str, verdict: bool, reason: str) -> None:
        now = self._clock()
        key = (source, verdict)
        if now - self._last_logged.get(key, float("-inf")) < self._log_every_s:
            return
        self._last_logged[key] = now
        logger.info("head move %s: %s (%s)", "allowed" if verdict else "refused", source, reason)
