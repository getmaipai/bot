"""Shared fakes for the offline-ladder suites: an injected clock and a
recording clip speaker. Nothing here sleeps or touches a network."""

from __future__ import annotations


class FakeClock:
    """A monotonic clock and a wall clock that only move when told to."""

    def __init__(self, start: float = 1000.0, wall_start: float = 1_800_000_000.0) -> None:
        self.now = start
        self.wall = wall_start

    def __call__(self) -> float:
        return self.now

    def wall_clock(self) -> float:
        return self.wall

    def advance(self, seconds: float) -> None:
        self.now += seconds
        self.wall += seconds


class FakeSpeaker:
    """The clip speaker's seam: records clip ids instead of playing them.
    ``available`` is the set of ids the (unrendered) bundle could say."""

    def __init__(self, available: set[str] | None = None) -> None:
        self.available = available
        self.said: list[list[str]] = []

    def can_say(self, clip_ids) -> bool:
        return self.available is None or all(c in self.available for c in clip_ids)

    def say(self, clip_ids, *, stop_event=None) -> bool:
        self.said.append(list(clip_ids))
        return True
