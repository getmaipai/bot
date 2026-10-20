"""The self-test's read-only view of the uplink: hearing (frames, bytes,
peak) and wake-word (detect) counts, without ever touching audio."""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest

from maipai_body.bodies.stackchan.uplink_stats import UplinkStats


class _FakeClock:
    """A monotonic clock whose ``sleep`` advances it and fires any callback
    scheduled at or before the new time, so a frame can arrive mid-window."""

    def __init__(self) -> None:
        self.now = 0.0
        self._events: list[tuple[float, Callable[[], None]]] = []

    def __call__(self) -> float:
        return self.now

    def at(self, when: float, fn: Callable[[], None]) -> None:
        self._events.append((when, fn))

    def sleep(self, seconds: float) -> None:
        target = self.now + seconds
        due = sorted((t, fn) for t, fn in self._events if t <= target)
        self._events = [(t, fn) for t, fn in self._events if t > target]
        for _, fn in due:
            fn()
        self.now = target


def _stats(clock: _FakeClock | None = None) -> tuple[UplinkStats, _FakeClock]:
    clock = clock or _FakeClock()
    return UplinkStats(clock=clock, sleep=clock.sleep), clock


def test_window_returns_only_frames_and_peak_recorded_during_it():
    stats, clock = _stats()
    stats.record_frame(640, 0.9)  # before the window: must be ignored
    clock.at(0.15, lambda: stats.record_frame(640, 0.3))
    clock.at(0.25, lambda: stats.record_frame(640, 0.6))
    frames, peak = stats.window(0.3)
    assert frames == 2
    assert peak == 0.6
    assert clock.now == pytest.approx(0.3)


def test_window_is_empty_when_nothing_arrives():
    stats, clock = _stats()
    stats.record_frame(640, 0.8)
    frames, peak = stats.window(0.1)
    assert (frames, peak) == (0, 0.0)
    assert clock.now == pytest.approx(0.1)


def test_window_keeps_the_maximum_peak_not_the_last():
    stats, clock = _stats()
    clock.at(0.05, lambda: stats.record_frame(640, 0.9))
    clock.at(0.15, lambda: stats.record_frame(640, 0.2))
    frames, peak = stats.window(0.2)
    assert frames == 2
    assert peak == 0.9


def test_peak_is_clamped_to_zero_and_one():
    stats, clock = _stats()
    clock.at(0.05, lambda: stats.record_frame(640, 1.7))
    frames, peak = stats.window(0.1)
    assert frames == 1
    assert peak == 1.0

    stats, clock = _stats()
    clock.at(0.05, lambda: stats.record_frame(640, -0.4))
    frames, peak = stats.window(0.1)
    assert peak == 0.0


def test_reset_window_zeroes_the_window_and_totals_survive():
    stats, clock = _stats()
    stats.record_frame(100, 0.5)
    stats.record_detect()
    stats.reset_window()
    frames, peak = stats.window(0.1)
    assert (frames, peak) == (0, 0.0)
    assert stats.total_frames == 1
    assert stats.total_bytes == 100
    assert stats.total_detects == 1

    stats.record_frame(50, 0.1)
    stats.record_detect()
    assert stats.total_frames == 2
    assert stats.total_bytes == 150
    assert stats.total_detects == 2
    clock.at(0.25, stats.record_detect)  # mid-wait: the clock is at 0.1 now
    assert stats.wait_detect(0.2) is True
    assert stats.total_detects == 3


def test_wait_detect_true_when_a_detect_lands_mid_wait():
    stats, clock = _stats()
    clock.at(0.15, stats.record_detect)
    assert stats.wait_detect(0.3) is True
    assert stats.total_detects == 1


def test_wait_detect_false_when_no_detect_arrives():
    stats, clock = _stats()
    assert stats.wait_detect(0.3) is False
    assert clock.now == pytest.approx(0.3)
    assert stats.total_detects == 0


def test_totals_are_thread_safe_under_concurrent_recording():
    stats = UplinkStats()  # real clock, but record_frame never sleeps

    def worker() -> None:
        for _ in range(1000):
            stats.record_frame(640, 0.5)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert stats.total_frames == 4000
    assert stats.total_bytes == 4000 * 640
