"""How the robot reacts when its orientation changes.

The unit reports a gravity axis. This module maps that axis to a pose and lets the caller
translate the pose into the unit's face, screen rotation and motion controls.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Mapping

logger = logging.getLogger("maipai_body.bodies.stackchan.orientation")

POSES = ("upright", "left_side", "right_side", "upside_down", "face_down", "on_back")
AXIS_POSES: dict[str, str] = {
    "-y": "upright",
    "+y": "upside_down",
    "+x": "left_side",
    "-x": "right_side",
    "-z": "face_down",
    "+z": "on_back",
}
FACE_FOR_POSE = {
    "upright": "neutral",
    "left_side": "doubt",
    "right_side": "doubt",
    "upside_down": "surprised",
    "face_down": "sleepy",
    "on_back": "sleepy",
}
LINE_GAP_S = 120.0
FACE_REFRESH_S = 5.0

LINE_POOLS = {
    "left_side": (
        "Whoa, the whole room is sideways!",
        "Tilting! Hello from my side.",
        "Sideways is fine. Kind of cozy.",
    ),
    "right_side": (
        "Whoa, the whole room is sideways!",
        "Tilting! Hello from my side.",
        "Sideways is fine. Kind of cozy.",
    ),
    "upside_down": (
        "Everything is upside down! Hi!",
        "New view! The ceiling is very plain.",
        "Is it me or is the floor on top?",
    ),
    "face_down": (
        "It is very dark down here.",
        "Hello, floor. I can't see a thing.",
        "Face down, nose to the table.",
    ),
    "on_back": (
        "Now I'm looking at the ceiling.",
        "Lying back. Very relaxing.",
        "Ahh, a nice long stare at the ceiling.",
    ),
    "upright": (
        "Ahh, that's better.",
        "Back on my feet. Thank you!",
        "Right side up again!",
    ),
}


def pose_for_axis(axis: str | None) -> str | None:
    """Return the calibrated pose for an axis, or None when it is unknown."""
    return AXIS_POSES.get(axis) if isinstance(axis, str) else None


class OrientationReactions:
    """Decides what the robot shows and says; the callables do it."""

    def __init__(
        self,
        *,
        face: Callable[[str], object],
        say: Callable[[str], bool],
        rotate: Callable[[int], object],
        hold_motion: Callable[[bool], object],
        quiet: Callable[[], bool] = lambda: False,
        busy: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self._face = face
        self._say = say
        self._rotate = rotate
        self._hold_motion = hold_motion
        self._quiet = quiet
        self._busy = busy
        self._clock = clock
        self._rng = rng or random.Random()
        self._pose = "upright"
        self._last_line: str | None = None
        self._last_spoken_at = float("-inf")
        self._last_face_at = float("-inf")

    @property
    def pose(self) -> str:
        return self._pose

    def on_event(self, extra: Mapping[str, object]) -> bool:
        """Apply a changed orientation and return whether the pose changed."""
        axis = extra.get("axis")
        if not isinstance(axis, str):
            return False
        pose = pose_for_axis(axis)
        if pose is None or pose == self._pose:
            return False

        self._pose = pose
        logger.info("StackChan orientation: %s", pose)
        self._rotate(180 if pose == "upside_down" else 0)
        self._hold_motion(pose != "upright")
        if not self._busy():
            self._send_face()
        if not self._quiet() and not self._busy():
            now = self._clock()
            if now - self._last_spoken_at >= LINE_GAP_S:
                choices = [line for line in LINE_POOLS[pose] if line != self._last_line]
                line = self._rng.choice(choices)
                if self._say(line):
                    self._last_line = line
                    self._last_spoken_at = now
        return True

    def _send_face(self) -> None:
        self._face(FACE_FOR_POSE[self._pose])
        self._last_face_at = self._clock()

    def tick(self) -> None:
        """Refresh the pose face while the robot remains away from upright."""
        if self._pose == "upright" or self._busy():
            return
        if self._clock() - self._last_face_at >= FACE_REFRESH_S:
            self._send_face()

    def reset(self) -> None:
        """Restore the boot pose and clear orientation controls without speech."""
        was_upright = self._pose == "upright"
        self._pose = "upright"
        self._rotate(0)
        if not was_upright:
            self._hold_motion(False)
            self._face("neutral")
            self._last_face_at = self._clock()
