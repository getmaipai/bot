"""A hard breaker for the robot's canned error lines ("I couldn't understand that...").

The apology must never loop. Rules, all clock-injected and per device:

* at most once per ``cooldown_s`` (60 s);
* never when the previous thing said was the same apology;
* never within ``speech_gap_s`` (3 s) of any other speech output;
* a circuit breaker: more than ``max_in_window`` requests in ``window_s`` (2 min) silences it
  until the next real final transcript (``note_real_final``), with one WARNING line.

Every suppression is counted and logged at INFO.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable

logger = logging.getLogger("maipai_body.bodies.stackchan.error_line")


class ErrorLineBreaker:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        cooldown_s: float = 60.0,
        speech_gap_s: float = 3.0,
        window_s: float = 120.0,
        max_in_window: int = 3,
    ) -> None:
        self._clock = clock
        self.cooldown_s = cooldown_s
        self.speech_gap_s = speech_gap_s
        self.window_s = window_s
        self.max_in_window = max_in_window
        self._asked: deque[float] = deque()
        self._last_error_at = float("-inf")
        self._last_speech_at = float("-inf")
        self._last_was_error = False
        self._tripped = False
        self.suppressed = 0

    def note_speech(self) -> None:
        """Something other than the apology was just spoken."""
        self._last_speech_at = self._clock()
        self._last_was_error = False

    def note_real_final(self) -> None:
        """A real transcript arrived: the person is talking, so the breaker resets."""
        self._asked.clear()
        self._tripped = False
        self._last_was_error = False

    def allow(self) -> bool:
        """Whether the apology may be spoken now; records the request either way."""
        now = self._clock()
        while self._asked and now - self._asked[0] > self.window_s:
            self._asked.popleft()
        self._asked.append(now)
        reason = None
        if self._tripped:
            reason = "breaker open"
        elif len(self._asked) > self.max_in_window:
            self._tripped = True
            logger.warning(
                "error line suppressed: %d requests in %.0f s; silent until the next real "
                "transcript",
                len(self._asked),
                self.window_s,
            )
            reason = "breaker tripped"
        elif self._last_was_error:
            reason = "the last thing said was the same line"
        elif now - self._last_error_at < self.cooldown_s:
            reason = "cooldown"
        elif now - self._last_speech_at < self.speech_gap_s:
            reason = "speech just played"
        if reason is not None:
            self.suppressed += 1
            logger.info(
                "error line suppressed (%d in last %.0f s): %s",
                len(self._asked),
                self.window_s,
                reason,
            )
            return False
        self._last_error_at = now
        self._last_was_error = True
        self._last_speech_at = now
        return True
