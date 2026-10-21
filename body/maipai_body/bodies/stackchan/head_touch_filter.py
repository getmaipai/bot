"""Ignore the head sensor's phantom touches (owner report 2026-10-21).

The CoreS3 head touch strip fires a lone "head_touch" every 10 seconds or so with nobody there
(the host log showed a "petted" line about every 10 to 12 s, which is the 10 s pet cooldown
sampling a stream that is faster). A real stroke gives a burst: several events in one look, a
repeat within a few seconds, or, from firmware that measures it, a contact held for 400 ms or more.
A lone event with none of those is dropped here, so it neither wakes the robot nor earns a heart,
and one INFO line a minute says how many were dropped.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

logger = logging.getLogger("maipai_body.bodies.stackchan.head_touch_filter")

HEAD_KINDS = frozenset({"head_touch", "head_swipe_forward", "head_swipe_back"})
# The host reads the unit's queue about every 2 s, so a repeat within 3 s shows in the next look.
REPEAT_WINDOW_S = 4.5
HELD_MS = 400
LOG_EVERY_S = 60.0


class HeadTouchFilter:
    def __init__(self) -> None:
        self._lone_at: float | None = None
        self._ignored = 0
        self._last_log = float("-inf")

    def accept(self, now: float, events: Iterable) -> list:
        """The events worth acting on: real head touches and everything that is not a head touch."""
        events = list(events)
        head = [e for e in events if getattr(e, "kind", None) in HEAD_KINDS]
        if not head:
            return events
        if self._is_real(now, head):
            self._lone_at = None
            return events
        self._lone_at = now
        self._ignored += 1
        if now - self._last_log >= LOG_EVERY_S:
            self._last_log = now
            logger.info(
                "StackChan ignored %d lone head touch%s (phantom filter)",
                self._ignored,
                "" if self._ignored == 1 else "es",
            )
            self._ignored = 0
        return [e for e in events if getattr(e, "kind", None) not in HEAD_KINDS]

    def _is_real(self, now: float, head: list) -> bool:
        if len(head) >= 2:
            return True
        extra = getattr(head[0], "extra", None) or {}
        if extra.get("strong") in (1, True):
            return True  # the unit's recogniser saw a touch that reached reading 2 or more
        held = extra.get("held_ms")
        if isinstance(held, int) and not isinstance(held, bool) and held >= HELD_MS:
            return True
        return self._lone_at is not None and now - self._lone_at <= REPEAT_WINDOW_S
