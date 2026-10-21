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
_PICTURE = re.compile(
    r"^(what do you see|what can you see|what are you seeing|what am i holding|"
    r"what am i showing you|look at this|take a look at this|what is this|what is that|"
    r"what'?s this|what'?s that|what do i have|what is in my hand|what'?s in my hand)$"
)
_FILLERS = re.compile(r"\b(please|ok|okay|hey|hi|um|uh|now|stack ?chan|can you tell me)\b")

YES = (
    "Yes! I can see you right there.",
    "Yes, there you are!",
    "I can see you, hi!",
)
NOBODY = (
    "I can't spot anyone right now, but my camera is on.",
    "Not at the moment. My camera is on, so step into view and I'll find you.",
)
CAMERA_OFF = (
    "My camera is off right now.",
    "My camera is turned off at the moment.",
)
NOT_READY = ("My camera is on, but my face finding isn't ready yet.",)
PICTURES_LATER = (
    "I can look, but I can't describe pictures yet.",
    "I can look at you, but I can't tell you what's in a picture yet.",
)


class SightAnswers:
    def __init__(
        self,
        *,
        face_age: Callable[[], float | None],
        camera_on: Callable[[], bool],
        detector_ready: Callable[[], bool] = lambda: True,
        rng: random.Random | None = None,
    ) -> None:
        self._face_age = face_age
        self._camera_on = camera_on
        self._detector_ready = detector_ready
        self._rng = rng or random.Random()
        self._last: dict[str, str] = {}

    def answer(self, text: str | None) -> str | None:
        """The line to say, or None when the words are not a sight question."""
        spoken = re.sub(r"[^\w' ]+", " ", (text or "").lower())
        spoken = re.sub(r"\s+", " ", _FILLERS.sub(" ", spoken)).strip()
        if not spoken:
            return None
        if _PICTURE.match(spoken):
            return self._pick("pictures", PICTURES_LATER)
        if not _CAN_SEE_ME.search(spoken):
            return None
        if not self._camera_on():
            return self._pick("off", CAMERA_OFF)
        age = self._face_age()
        if age is not None and age <= FACE_FRESH_S:
            return self._pick("yes", YES)
        if not self._detector_ready():
            return self._pick("not_ready", NOT_READY)
        return self._pick("nobody", NOBODY)

    def _pick(self, key: str, lines: tuple[str, ...]) -> str:
        choices = [line for line in lines if line != self._last.get(key)] or list(lines)
        self._last[key] = self._rng.choice(choices)
        return self._last[key]
