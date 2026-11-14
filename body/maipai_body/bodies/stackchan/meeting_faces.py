"""Small host-side face choices for explicit person meeting events."""

from __future__ import annotations

import threading
from collections.abc import Callable


def face_for_meeting(kind: str) -> tuple[str, ...]:
    return {
        "arrived": ("surprised", "happy"),
        "recognised": ("happy",),
        "child": ("excited",),
        "stranger": ("curious",),
        "left": ("sad",),
        "returned_after_long": ("excited",),
    }.get(kind, ("neutral",))


class MeetingFaces:
    def __init__(self, show_face: Callable[[str], object], *, timer=threading.Timer) -> None:
        self._show_face = show_face
        self._timer = timer

    def on_meeting(self, kind: str) -> None:
        faces = face_for_meeting(kind)
        self._show_face(faces[0])
        if len(faces) > 1:
            timer = self._timer(0.35, lambda: self._show_face(faces[1]))
            timer.daemon = True
            timer.start()
        timer = self._timer(3.0, lambda: self._show_face("neutral"))
        timer.daemon = True
        timer.start()


__all__ = ["MeetingFaces", "face_for_meeting"]
