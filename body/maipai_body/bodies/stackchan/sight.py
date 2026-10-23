"""Honest answers to "can you see me?" and the picture questions the robot cannot answer yet.

The robot has a camera and finds faces locally, so it never says a flat "I can't see". It answers
from what the host really knows: a face seen a moment ago, the camera being off, or nobody in view.
Questions that need a described picture ("what am I holding?") get one plain line until Home can
describe a frame; nothing here sends a frame anywhere.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable

FACE_FRESH_S = 10.0  # "I can see you" only for a face seen this recently

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


class SightAnswers:
    def __init__(
        self,
        *,
        face_age: Callable[[], float | None],
        camera_on: Callable[[], bool],
        light: Callable[[], str | None] = lambda: None,
        camera_running_s: Callable[[], float | None] = lambda: STARTING_S,
        watching: Callable[[], bool] = lambda: False,
        rng: random.Random | None = None,
    ) -> None:
        self._face_age = face_age
        self._camera_on = camera_on
        self._light = light
        self._camera_running_s = camera_running_s
        self._watching = watching
        self._rng = rng or random.Random()
        self._last: dict[str, str] = {}

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
                    return f"It is {room} here and I can see someone."
                return f"It is {room} here and I can't see anyone right now."
            if room:
                return (
                    f"my camera is on, it is {room} here, but I cannot describe the room yet "
                    "(pictures are not being analysed)"
                )
            return (
                "my camera is on, but I cannot describe the room yet "
                "(pictures are not being analysed)"
            )
        if room:
            return (
                f"I can't spot anyone right now. My camera is on and {room}, "
                "but I can't describe it yet."
            )
        return "I can't spot anyone right now. My camera is on, but I can't describe the room yet."

    def _pick(self, key: str, lines: tuple[str, ...]) -> str:
        choices = [line for line in lines if line != self._last.get(key)] or list(lines)
        self._last[key] = self._rng.choice(choices)
        return self._last[key]
