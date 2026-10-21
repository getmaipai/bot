"""A spoken "stop" heard while listening ends the turn on the robot, without asking the hub.

"Stop", "StackChan, stop", "be quiet", "never mind" and the like are a request to stop, not a
question for the model: the hub's answer to them was a chatty reply. Only a whole utterance that is
one of these phrases counts, so "stop the music in the kitchen" still goes to the hub.
"""

from __future__ import annotations

import re

_FILLERS = re.compile(r"\b(please|ok|okay|hey|hi|um|uh|now|thanks|thank you|stack ?chan)\b")

_PHRASES = frozenset(
    {
        "stop",
        "stop it",
        "stop talking",
        "stop listening",
        "stop that",
        "be quiet",
        "quiet",
        "never mind",
        "nevermind",
        "cancel",
        "that's enough",
        "that is enough",
        "enough",
    }
)


def is_stop_phrase(text: str | None) -> bool:
    """True when the whole utterance is a stop phrase (fillers such as "StackChan" ignored)."""
    spoken = re.sub(r"[^\w' ]+", " ", (text or "").lower().replace("-", " "))
    spoken = re.sub(r"\s+", " ", _FILLERS.sub(" ", spoken)).strip()
    return spoken in _PHRASES
