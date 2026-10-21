"""Why the head is pointed where it is, and honest answers to "what are you looking at?".

The head code notes a reason whenever it moves. A question about the gaze is answered from that
reason and nothing else: the robot never claims to see something it did not detect, and never
uses surveillance wording. "What do you see?" is a vision question and goes on to the hub.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from enum import StrEnum


class GazeReason(StrEnum):
    TRACK = "track"  # following a face
    COMMAND = "command"  # a spoken "look left"
    SEARCH = "search"  # a face it was following disappeared
    SWEEP = "sweep"  # idle wandering is allowed
    THINKING = "thinking"  # the thinking gaze during a chat wait
    REST = "rest"  # asleep, drowsy or night
    IDLE = "idle"  # level, nothing in particular


RECENT_S = {
    GazeReason.TRACK: 10.0,
    GazeReason.COMMAND: 60.0,
    GazeReason.SEARCH: 20.0,
    GazeReason.THINKING: 20.0,
}

_ASKS = re.compile(
    r"\b(what|where|who|why)\b.*\b(are you|were you|is it that you're|you)\b.*"
    r"\b(looking|staring|gazing|watching)\b"
)
_NOT_ASKS = re.compile(r"\b(see|read|show|tell me|describe)\b")

ANSWERS: dict[GazeReason, tuple[str, ...]] = {
    GazeReason.TRACK: (
        "I'm looking at you.",
        "Just looking at your face, hehe.",
        "At you! You're good company.",
    ),
    GazeReason.SEARCH: (
        "I was trying to find where you went.",
        "I lost you for a second and was looking for you.",
    ),
    GazeReason.SWEEP: (
        "Just looking around the room, taking in the sights.",
        "Nothing special, just having a look around.",
        "Admiring the room, honestly.",
    ),
    GazeReason.THINKING: (
        "Just looking around the room, taking in the sights.",
        "I look away a bit when I'm thinking.",
    ),
    GazeReason.REST: (
        "My eyes are mostly closed, I'm resting.",
        "I'm resting my eyes right now.",
    ),
    GazeReason.IDLE: (
        "Nothing in particular, just hanging out.",
        "Nothing really, just hanging out.",
        "Not much, just resting my head in the middle.",
    ),
}
_COMMAND_NAMES = {
    "left": "look left",
    "right": "look right",
    "up": "look up",
    "down": "look down",
    "around": "look around",
    "centre": "look straight ahead",
    "nod": "nod",
    "shake": "shake my head",
}


def is_gaze_question(text: str | None) -> bool:
    spoken = re.sub(r"\s+", " ", re.sub(r"[^\w' ]+", " ", (text or "").lower())).strip()
    return bool(spoken) and bool(_ASKS.search(spoken)) and not _NOT_ASKS.search(spoken)


class GazeState:
    """The reason of the last head move, with its time, and the honest answers."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        asleep: Callable[[], bool] = lambda: False,
        wandering: Callable[[], bool] = lambda: False,
        rng: random.Random | None = None,
    ) -> None:
        self._clock = clock
        self._asleep = asleep
        self._wandering = wandering
        self._rng = rng or random.Random()
        self.reason = GazeReason.IDLE
        self.detail: str | None = None
        self.at = float("-inf")
        self._last_answer: dict[GazeReason, str] = {}

    def note(self, reason: GazeReason, detail: str | None = None) -> None:
        self.reason, self.detail, self.at = reason, detail, self._clock()

    def current(self) -> GazeReason:
        """What the head is doing now, from the last reason and how old it is."""
        if self._asleep():
            return GazeReason.REST
        age = self._clock() - self.at
        limit = RECENT_S.get(self.reason)
        if limit is not None and age <= limit:
            return self.reason
        return GazeReason.SWEEP if self._wandering() else GazeReason.IDLE

    def answer(self, text: str | None) -> str | None:
        """The reply to a gaze question, or None when the words are not one."""
        if not is_gaze_question(text):
            return None
        reason = self.current()
        if reason is GazeReason.COMMAND:
            what = _COMMAND_NAMES.get(self.detail or "", "look there")
            return f"You asked me to {what}!"
        choices = [c for c in ANSWERS[reason] if c != self._last_answer.get(reason)]
        line = self._rng.choice(choices or list(ANSWERS[reason]))
        self._last_answer[reason] = line
        return line
