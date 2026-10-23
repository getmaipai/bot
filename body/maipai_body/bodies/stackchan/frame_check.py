"""Why does the face detector find nobody? A once-a-minute log line, nothing stored.

The camera frames stream in at about 3 KB each and the detector runs on them (host log
2026-10-22), yet no face is found with the owner in view. A rotated, mirrored or colour-swapped
frame defeats the detector. While no face is found, every ``EVERY_S`` seconds the same frame is
tried in a few other forms and only the detector's best score for each form is kept, per minute.
The frame is never written anywhere and the score is the only thing that leaves this function.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import numpy as np
import numpy.typing as npt

logger = logging.getLogger("maipai_body.bodies.stackchan.frame_check")

EVERY_S = 10.0
REPORT_S = 60.0


def _forms(frame: npt.NDArray[np.uint8]) -> dict[str, npt.NDArray[np.uint8]]:
    return {
        "rot90": np.ascontiguousarray(np.rot90(frame, 1)),
        "rot180": np.ascontiguousarray(np.rot90(frame, 2)),
        "rot270": np.ascontiguousarray(np.rot90(frame, 3)),
        "mirror": np.ascontiguousarray(frame[:, ::-1]),
        "flip": np.ascontiguousarray(frame[::-1]),
        "rgb": np.ascontiguousarray(frame[:, :, ::-1]),
    }


class FrameCheck:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last_try = float("-inf")
        self._since: float | None = None
        self._best: dict[str, float] = {}
        self._detection_off = False
        self._size = ""
        self._bytes = 0
        self._frames = 0

    def note(self, detector: Any, frame: npt.NDArray[np.uint8], nbytes: int) -> None:
        """A frame in which no face was found; ``detector.best_score`` follows its last detect."""
        if detector is None or not hasattr(detector, "best_score"):
            self._detection_off = True
            height, width = frame.shape[:2]
            self._size = f"{width}x{height}"
            self._bytes += nbytes
            self._frames += 1
            return
        height, width = frame.shape[:2]
        self._size = f"{width}x{height}"
        self._bytes += nbytes
        self._frames += 1
        self._best["as-is"] = max(self._best.get("as-is", 0.0), float(detector.best_score))
        now = self._clock()
        if now - self._last_try < EVERY_S:
            return
        self._last_try = now
        for name, form in _forms(frame).items():
            try:
                detector.detect(form)
            except Exception:
                continue
            self._best[name] = max(self._best.get(name, 0.0), float(detector.best_score))

    def report(self, now: float) -> str | None:
        if self._since is None:
            self._since = now
            return None
        if now - self._since < REPORT_S:
            return None
        self._since = now
        if not self._frames:
            return None
        scores = (
            ", ".join(f"{name} {score:.2f}" for name, score in self._best.items())
            if self._best and not self._detection_off
            else "face detection is off (model not loaded)"
        )
        line = (
            f"StackChan frame check: {self._size}, {self._bytes / self._frames / 1024:.1f} KB a "
            f"frame; best face score with nobody found: {scores}"
        )
        self._best = {}
        self._detection_off = False
        self._bytes = self._frames = 0
        return line
