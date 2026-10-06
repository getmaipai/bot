"""EYES-02: ``LiveCaptureTap``, the live-capture cue's source of truth.

The tap wraps the real client behind the ``AudioIO`` and ``Camera`` seams
and forwards every call unchanged, so a mic open, a frame read or a daemon
camera tracker cannot happen without the live cue hearing about it. Every
consumer gets the tap, not the client (``tests/test_indicator_live.py``
enumerates each mic-open and frame-read call site and fails on a bypass).

What it reports, as ``CaptureFacts``:

- ``mic_live``: the mic is open AND the voice is being sent to the hub, that
  is, inside ``sending_to_hub()``, which the run loop holds around the STT
  stream only. Wake-word scoring stays on the robot and is not live. This is a
  software indicator: it is true to what this program sends, and it is not a
  hardware mute or a hardware light.
- ``camera_tracking``: the daemon's face tracker is enabled, so the camera is
  in use inside the daemon, out of this process's own reads.
- ``camera_read_at``: when this program last read a frame, on the tap's clock.

The cue goes up BEFORE a capture starts and comes down AFTER it ends, never
the other way round. It reads no turn, playback or tracking state.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("maipai_body.indicator.live")


@dataclass(frozen=True)
class CaptureFacts:
    mic_live: bool = False
    camera_tracking: bool = False
    camera_read_at: float | None = None


class LiveCaptureTap:
    def __init__(self, inner: Any, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._inner = inner
        self._clock = clock
        self._lock = threading.Lock()
        self._mic_open = False
        self._sending = 0
        self._tracking = False
        self._camera_read_at: float | None = None
        self._subscribers: list[Callable[[CaptureFacts], None]] = []

    # -- the readers' side ----------------------------------------------

    def subscribe(self, callback: Callable[[CaptureFacts], None]) -> None:
        """Call ``callback`` with the facts after each change, on the changing thread."""
        with self._lock:
            self._subscribers.append(callback)

    def facts(self) -> CaptureFacts:
        with self._lock:
            return self._facts_locked()

    def _facts_locked(self) -> CaptureFacts:
        return CaptureFacts(
            mic_live=self._mic_open and self._sending > 0,
            camera_tracking=self._tracking,
            camera_read_at=self._camera_read_at,
        )

    def _emit(self) -> None:
        with self._lock:
            facts = self._facts_locked()
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(facts)
            except Exception:
                logger.warning("capture subscriber failed", exc_info=True)

    @contextmanager
    def sending_to_hub(self) -> Iterator[None]:
        """Held while the voice is being sent to the hub; nests."""
        with self._lock:
            self._sending += 1
        self._emit()
        try:
            yield
        finally:
            with self._lock:
                self._sending -= 1
            self._emit()

    # -- AudioIO, capture side ------------------------------------------

    def start_recording(self) -> None:
        with self._lock:
            self._mic_open = True
        self._emit()
        try:
            self._inner.start_recording()
        except BaseException:
            with self._lock:
                self._mic_open = False
            self._emit()
            raise

    def stop_recording(self) -> None:
        try:
            self._inner.stop_recording()
        finally:
            with self._lock:
                self._mic_open = False
            self._emit()

    def get_audio_sample(self) -> Any:
        return self._inner.get_audio_sample()

    # -- Camera ---------------------------------------------------------

    def get_frame(self) -> Any:
        self._note_read()
        return self._inner.get_frame()

    def get_frame_jpeg(self) -> Any:
        self._note_read()
        return self._inner.get_frame_jpeg()

    def _note_read(self) -> None:
        with self._lock:
            self._camera_read_at = self._clock()
        self._emit()

    # -- the daemon's own camera use ------------------------------------

    def enable_tracking(self, weight: float = 1.0) -> None:
        with self._lock:
            self._tracking = True
        self._emit()
        try:
            self._inner.enable_tracking(weight)
        except BaseException:
            with self._lock:
                self._tracking = False
            self._emit()
            raise

    def disable_tracking(self) -> None:
        try:
            self._inner.disable_tracking()
        finally:
            with self._lock:
                self._tracking = False
            self._emit()

    def __getattr__(self, name: str) -> Any:
        # Only reached for names the tap does not define: everything else of the
        # client (head, antennas, the state feed, playback, the IMU) passes through.
        return getattr(self._inner, name)
