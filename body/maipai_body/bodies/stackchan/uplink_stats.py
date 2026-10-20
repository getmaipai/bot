"""Uplink statistics the self-test can read: hearing (frames, bytes, peak)
and wake-word (detect) counts for the StackChan uplink.

Counts only, never audio. Thread-safe: every counter sits behind one lock,
so the audio thread and the self-test thread can share one instance.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

POLL_S = 0.1


class UplinkStats:
    """The self-test's read-only view of the uplink.

    The audio thread calls :meth:`record_frame` per uplink frame and
    :meth:`record_detect` when the device reports a wake word (``listen
    detect``); the self-test reads them back through :meth:`window` and
    :meth:`wait_detect`. Window counters are what the self-test looks at;
    the lifetime totals are never reset.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._window_frames = 0
        self._window_bytes = 0
        self._window_peak = 0.0
        self._window_detects = 0
        self._total_frames = 0
        self._total_bytes = 0
        self._total_detects = 0

    @property
    def total_frames(self) -> int:
        """Frames recorded since this instance was created."""
        with self._lock:
            return self._total_frames

    @property
    def total_bytes(self) -> int:
        """Uplink bytes recorded since this instance was created."""
        with self._lock:
            return self._total_bytes

    @property
    def total_detects(self) -> int:
        """Wake-word detects recorded since this instance was created."""
        with self._lock:
            return self._total_detects

    def record_frame(self, nbytes: int, peak: float = 0.0) -> None:
        """One uplink frame: its bytes, and the peak (clamped to 0..1)."""
        peak = min(1.0, max(0.0, peak))
        with self._lock:
            self._window_frames += 1
            self._window_bytes += nbytes
            self._window_peak = max(self._window_peak, peak)
            self._total_frames += 1
            self._total_bytes += nbytes

    def record_detect(self) -> None:
        """The device sent ``listen detect``: a wake word was heard."""
        with self._lock:
            self._window_detects += 1
            self._total_detects += 1

    def reset_window(self) -> None:
        """Zero the window counters; the lifetime totals are untouched."""
        with self._lock:
            self._window_frames = 0
            self._window_bytes = 0
            self._window_peak = 0.0
            self._window_detects = 0

    def window(self, seconds: float) -> tuple[int, float]:
        """Watch the uplink for ``seconds``; return (frames, peak) in it."""
        self.reset_window()
        self._sleep_for(seconds)
        with self._lock:
            return self._window_frames, self._window_peak

    def wait_detect(self, seconds: float) -> bool:
        """Wait up to ``seconds`` for a wake word; True if one arrived."""
        self.reset_window()
        start = self._clock()
        while self._clock() - start < seconds:
            self._sleep(POLL_S)
            with self._lock:
                if self._window_detects > 0:
                    return True
        with self._lock:
            return self._window_detects > 0

    def _sleep_for(self, seconds: float) -> None:
        start = self._clock()
        while self._clock() - start < seconds:
            self._sleep(POLL_S)
