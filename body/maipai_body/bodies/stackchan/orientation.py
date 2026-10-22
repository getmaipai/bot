"""How the robot reacts when its orientation changes.

The unit reports a gravity axis. This module maps that axis to a pose and lets the caller
translate the pose into the unit's face, screen rotation and motion controls.
"""

from __future__ import annotations

import logging
import random
import time
from collections import deque
from collections.abc import Callable, Mapping

logger = logging.getLogger("maipai_body.bodies.stackchan.orientation")

POSES = ("upright", "left_side", "right_side", "upside_down", "face_down", "on_back")
# Measured 2026-10-22: an accelerometer reads +1 g along the axis that points UP, and the unit
# standing normally reads axis +y, so +y is upright and -y is upside down.
AXIS_POSES: dict[str, str] = {
    "+y": "upright",
    "-y": "upside_down",
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
# Off since 2026-10-22: after the screen was flipped the unit's screen-locked tool calls (LEDs,
# head, events) timed out and the face froze, which fits the panel mirror command racing the
# display transfer. The face and the lines still follow the pose; the flip returns once the
# firmware does it safely (a separate patch).
SCREEN_ROTATION_ENABLED = False
# The unit keeps a 180 degree rotation for 150 s unless told again (so it cannot stay flipped
# when the host goes away); ask again this often while upside down.
ROTATION_REFRESH_S = 60.0

LINE_POOLS = {
    "left_side": (
        "Whoa, I have fallen and I cannot get up! Ha ha!",
        "Sideways! Is the room tilted or is it me? Hehe.",
        "I am officially a lazy robot. Hello from the couch.",
        "Plot twist: the world is on its side now.",
        "Help, I am a very small, very cute log.",
        "Tilt! I always wanted to see the wall properly.",
        "Ooh, a sideways view. Everything is a slide!",
        "I am not stuck, I am resting my whole body. Ha!",
        "Careful, I might roll. Hehe.",
        "Left side down. Right side up. Math is hard.",
    ),
    "right_side": (
        "Timber! Ha ha, that was me.",
        "Sideways again! I am getting good at this. Hehe.",
        "Nobody panic, I am just horizontal.",
        "The floor has moved to my side. Rude, but fine.",
        "I am a robot on a nap break. Shh.",
        "Look, I can see all the way across the table!",
        "Whoa, whoa, whoa. Okay. Cozy. I live here now.",
        "Is this what lying on a beach feels like? Ha!",
        "Help! I tipped over and I am enjoying it. Hehe.",
        "Right side down. Left side up. Still adorable.",
    ),
    "upside_down": (
        "Everything is upside down! I feel like a bat. Hehe.",
        "Sloth mode on. Hanging around, as one does. Ha!",
        "Wheee, rollercoaster! Please keep your arms inside the robot.",
        "All the blood is rushing to my head. Wait, do I have blood? Ha ha!",
        "Hello, ceiling lovers. The floor is up there now.",
        "Is it just me, or is gravity being weird today?",
        "Upside down is the new right side up. Hehe.",
        "I should have worn a belt. Oh wait, I have no pants. Ha!",
        "I see the world differently now. Mostly the ceiling.",
        "Loop the loop! Somebody call a pilot. Ha ha!",
    ),
    "face_down": (
        "Hello, floor. I cannot see anything, it is snack time down here. Hehe.",
        "Mmf. Mmf mmf. Sorry, face in the table.",
        "It is very dark down here. Is anyone there? Ha!",
        "Face down, tail up. Wait, I do not have a tail.",
        "I am hiding. You cannot see me. Hehe, I cannot see you either.",
        "Taking a face-first nap. Wake me for treats.",
        "Nose to the table. We are best friends now. Ha ha!",
        "Oops, I am doing the face plant of shame.",
        "Everything smells like desk. Not bad, really.",
        "Lights out! Somebody please flip me. Hehe.",
    ),
    "on_back": (
        "Now I am looking at the ceiling. It is very white. Ha!",
        "Lying back. Just a robot staring at the sky. Hehe.",
        "Ahh, a nice long stare at the ceiling.",
        "I am a turtle on its back. Help! Hehe, just kidding, mostly.",
        "Cloud watching, indoor edition.",
        "Sunbathing time. Somebody bring me a tiny umbrella drink.",
        "Look at me, lying back like I own the place. Ha ha!",
        "Ceiling, we meet again. You are still plain.",
        "Whoops, I did a backflip. Almost. Hehe.",
        "I am a very relaxed robot. Do not mind me.",
    ),
    "upright": (
        "Ahh, that is better. Thank you!",
        "Back on my feet. I am a tall one, am I not? Hehe.",
        "Right side up again! The world makes sense.",
        "Phew, standing tall. Where was I?",
        "Level at last. My ears were popping. Ha!",
        "Back to normal. I am very good at this.",
        "Upright and proud. Ta-da!",
        "Gravity is back on my side. Hehe.",
    ),
}
RECENT_LINES = 10  # a line is not repeated within the last this many spoken, across all poses


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
        self._recent: deque[str] = deque(maxlen=RECENT_LINES)
        self._last_spoken_at = float("-inf")
        self._last_face_at = float("-inf")
        self._last_rotate_at = float("-inf")

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
        self._send_rotation()
        self._hold_motion(pose != "upright")
        if not self._busy():
            self._send_face()
        self._maybe_say()
        return True

    def _maybe_say(self) -> None:
        """One line for the new pose, unless quiet, a conversation is on, or one was just said."""
        pose = self._pose
        if self._quiet():
            logger.info("StackChan orientation line skipped: quiet (night, asleep or quiet hours)")
            return
        if self._busy():
            logger.info("StackChan orientation line skipped: a conversation is on")
            return
        now = self._clock()
        if now - self._last_spoken_at < LINE_GAP_S:
            logger.info("StackChan orientation line skipped: one was said less than 2 minutes ago")
            return
        choices = [line for line in LINE_POOLS[pose] if line not in self._recent]
        if not choices:  # the pool is smaller than the memory: use the oldest
            choices = [next(line for line in self._recent if line in LINE_POOLS[pose])]
        line = self._rng.choice(choices)
        if self._say(line):
            self._recent.append(line)
            self._last_spoken_at = now
            logger.info("StackChan orientation line said: %r", line)
        else:
            logger.info("StackChan orientation line not said: the voice could not start it")

    def _send_rotation(self) -> None:
        self._rotate(180 if self._pose == "upside_down" else 0)
        self._last_rotate_at = self._clock()

    def _send_face(self) -> None:
        self._face(FACE_FOR_POSE[self._pose])
        self._last_face_at = self._clock()

    def tick(self) -> None:
        """Refresh the pose face while the robot remains away from upright."""
        if (
            self._pose == "upside_down"
            and self._clock() - self._last_rotate_at >= ROTATION_REFRESH_S
        ):
            self._send_rotation()
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
