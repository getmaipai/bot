"""Honest answers to "can you see me?" and the picture questions when Home gave no description.

The robot has a camera and finds faces locally, so it never says a flat "I can't see". It answers
from what the host really knows: a face seen a moment ago, the camera being off, or nobody in view.
Questions that need a described picture ("what am I holding?") normally go to Home with a picture
(vision_post.py); when that did not happen just now, the line here says so and invites another try.
Nothing here sends a frame anywhere.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable

FACE_FRESH_S = 10.0  # "I can see you" only for a face seen this recently
PERSON_FRESH_S = 10.0  # the Look detector saw a person (no face needed) this recently
OBJECTS_FRESH_S = (
    90.0  # "what do you see" answers from a look this young (the camera pauses in a turn)
)
MOTION_FRESH_S = 30.0  # something moved in the picture this recently: someone is probably there

_CAN_SEE_ME = re.compile(
    r"\b(can|could|do|did|are you able to)\b.*\b(see|spot|find|notice)\b"
    r".*\b(me|us|anyone|anybody)\b"
)
_LIGHT = re.compile(
    r"\b(is|are) (the |any |there a )?(light|lights|lamp|lamps)\b.*\b(on|off)\b|"
    r"\bis it (dark|bright|light|dim)\b|\bhow (bright|dark) is it\b|"
    r"\bturn(ed)? (the )?lights? (on|off)\b"
)
_PICTURE = re.compile(
    r"^(what do you see|what can you see|what are you seeing|what are you looking at|"
    r"what do you see in here|describe what you see|what is in front of you|"
    r"what'?s in front of you|"
    r"what am i holding|"
    r"what am i showing you|look at this|take a look at this|what is this|what is that|"
    r"what'?s this|what'?s that|what do i have|what is in my hand|what'?s in my hand)$"
)
_FILLERS = re.compile(r"\b(please|ok|okay|hey|hi|um|uh|now|stack ?chan|can you tell me)\b")

YES = (
    "Yes! I can see you right there.",
    "Yes, there you are!",
    "I can see you, hi!",
)
# No face, but the Look detector sees a person: they are there, the face is out of the picture.
PERSON_NO_FACE = (
    "I can see someone right in front of me, but not your face yet.",
    "Yes, I can see you, though not your face. Sit back a little and I'll find it.",
)
# No face, but the picture is changing: a person is probably there, too close or too low for a face.
MOVING = (
    "I can't see a face, but something is moving right in front of me. Is that you?",
    "Something is moving close to me, though I can't see a face. Lean back a bit so I can see you.",
)
CAMERA_OFF = (
    "My camera is off right now.",
    "My camera is turned off at the moment.",
)
STARTING_S = 60.0  # a camera that has streamed for less than this is still starting up
NOT_READY = (
    "My camera is just starting up. Ask me again in a few seconds.",
    "I'm just waking my camera up. Ask me again in a few seconds.",
)
# The camera has been running a while, but nothing here can describe the room: say so plainly.
ROOM_LOOKS = {
    "dark": "dark",
    "dim": "dim",
    "bright": "bright",
}
DARK = ("It looks dark in here, so the lights are probably off.",)
DIM = ("It's fairly dim in here.",)
BRIGHT = ("It looks bright in here, so the lights are probably on.",)
# Home describes a picture on request (vision_post.py); this is the line when that did not happen
# just now (no fresh picture, Home busy, or the picture refused), so the person simply asks again.
NO_LOOK = "I couldn't get a good look just now. Ask me again in a moment."


class SightAnswers:
    def __init__(
        self,
        *,
        face_age: Callable[[], float | None],
        camera_on: Callable[[], bool],
        light: Callable[[], str | None] = lambda: None,
        camera_running_s: Callable[[], float | None] = lambda: STARTING_S,
        watching: Callable[[], bool] = lambda: False,
        motion_age: Callable[[], float | None] = lambda: None,
        person_age: Callable[[], float | None] = lambda: None,
        objects: Callable[[float], list[dict] | None] = lambda _max_age_s: None,
        rng: random.Random | None = None,
    ) -> None:
        self._face_age = face_age
        self._camera_on = camera_on
        self._light = light
        self._camera_running_s = camera_running_s
        self._watching = watching
        self._motion_age = motion_age
        self._person_age = person_age
        self._objects = objects
        self._rng = rng or random.Random()
        self._last: dict[str, str] = {}

    def quick_look(self) -> str | None:
        """The instant answer to "what do you see" from the robot's own fast pass ("I see a person
        and a laptop."), or None when no young look named anything. Home's detailed sentence
        follows through the normal turn; this line is never logged."""
        from maipai_body.vision.look_fast import spoken_line

        if not self._camera_on():
            return None
        objects = self._objects(OBJECTS_FRESH_S)
        return spoken_line(objects) if objects else None

    def _person_seen(self) -> bool:
        age = self._person_age()
        return age is not None and age <= PERSON_FRESH_S

    def kind(self, text: str | None) -> str | None:
        """What sort of sight question this is: "light", "picture", "see_me", or None."""
        spoken = re.sub(r"[^\w' ]+", " ", (text or "").lower())
        spoken = re.sub(r"\s+", " ", _FILLERS.sub(" ", spoken)).strip()
        if not spoken:
            return None
        if _LIGHT.search(spoken):
            return "light"
        if _PICTURE.match(spoken):
            return "picture"
        if _CAN_SEE_ME.search(spoken):
            return "see_me"
        return None

    def answer(self, text: str | None) -> str | None:
        """The line to say from what this host knows alone, or None for other words.

        Used when Home cannot describe a picture (no scene is available)."""
        kind = self.kind(text)
        if kind is None:
            return None
        if not self._camera_on():
            return self._pick("off", CAMERA_OFF)
        if kind == "see_me":
            age = self._face_age()
            if age is not None and age <= FACE_FRESH_S:
                return self._pick("yes", YES)
            if self._person_seen():
                return self._pick("person", PERSON_NO_FACE)
        running = self._camera_running_s()
        if running is None or running < STARTING_S:
            return self._pick("not_ready", NOT_READY)
        bucket = self._light()
        if kind == "light":
            lines = {"dark": DARK, "dim": DIM, "bright": BRIGHT}.get(bucket or "")
            if lines:
                return self._pick(f"light_{bucket}", lines)
            return "My camera is on, but I can't tell how bright it is."
        room = ROOM_LOOKS.get(bucket or "")
        if kind == "picture":
            if room and self._watching():
                # The face detector is running, so "nobody" is an answer, not a gap.
                age = self._face_age()
                if age is not None and age <= FACE_FRESH_S:
                    return f"It is {room} here and I can see someone, but {NO_LOOK}"
                if self._person_seen():
                    return (
                        f"It is {room} here and I can see someone in front of me, "
                        f"though not a face, and {NO_LOOK}"
                    )
                if self._moving():
                    return (
                        f"It is {room} here and something is moving close to me, "
                        f"though I can't see a face, and {NO_LOOK}"
                    )
                return f"It is {room} here and I can't see anyone right now, but {NO_LOOK}"
            if room:
                return f"My camera is on and it is {room} here, but {NO_LOOK}"
            return f"My camera is on, but {NO_LOOK}"
        if self._person_seen():
            return self._pick("person", PERSON_NO_FACE)
        if self._moving():
            return self._pick("moving", MOVING)
        if room:
            return f"I can't spot anyone right now. My camera is on and it is {room} here."
        return "I can't spot anyone right now, but my camera is on."

    def _moving(self) -> bool:
        """Something moved in the picture a moment ago: a person whose face is out of view."""
        age = self._motion_age()
        return age is not None and age <= MOTION_FRESH_S

    def _pick(self, key: str, lines: tuple[str, ...]) -> str:
        choices = [line for line in lines if line != self._last.get(key)] or list(lines)
        self._last[key] = self._rng.choice(choices)
        return self._last[key]
