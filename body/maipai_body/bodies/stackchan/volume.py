"""Spoken volume control for the StackChan, answered on the robot without asking the hub.

"Turn it up", "quieter", "volume to 60" and "mute" change the speaker through the firmware's
``self.audio_speaker.set_volume`` tool. The firmware keeps the level across reboots; this module
only decides the new level. Levels are percent, kept between ``MIN_LEVEL`` and ``MAX_LEVEL`` so a
voice command can never make the robot inaudible by accident (mute is a separate word).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("maipai_body.bodies.stackchan.volume")

MIN_LEVEL = 20
MAX_LEVEL = 100
STEP = 15
DEFAULT_LEVEL = 60

_VOLUME = re.compile(r"\b(volume|sound level)\b")
_THE = r"(?:(?:the|your|my|that|this) )?"
_UP = re.compile(
    r"\b(louder|speak up|talk up|say that louder|"
    rf"(?:raise|increase|turn up|bump up|boost|crank up|up) {_THE}(?:volume|sound)|"
    rf"turn {_THE}(?:volume |sound |it )?up|volume up|more volume|"
    r"too (?:quiet|soft|low|faint|quietly|softly)|"
    r"can'?t hear|cannot hear|can not hear|couldn'?t hear|hard to hear|hardly hear|didn'?t hear)\b"
)
_DOWN = re.compile(
    r"\b(quieter|softer|more quietly|more softly|speak low|"
    rf"(?:lower|decrease|reduce|turn down|bring down|drop|down) {_THE}(?:volume|sound)|"
    rf"turn {_THE}(?:volume |sound |it )?down|volume down|less volume|"
    r"too loud|so loud|way too loud|not so loud|too noisy|you'?re loud|that'?s loud|"
    r"talk quieter|speak quieter|speak softer|talk softer)\b"
)
_MAX = re.compile(
    r"\b(max(?:imum)? volume|full volume|volume (?:to |at )?(?:max|maximum|full)|"
    r"as loud as you can|all the way up|turn it all the way up)\b"
)
_MUTE = re.compile(r"\b(mute|be quiet|silence|shush|shut up)\b")
_HALF = re.compile(r"\b(half|halfway|half way|fifty fifty)\b")
_QUARTER = re.compile(r"\b(quarter|a quarter)\b")
_DIGITS = re.compile(r"\b(\d{1,3})\s?(?:%|percent)?(?!\d)")
_LEVEL_CONTEXT = re.compile(r"\b(volume|sound|set|make|put|turn)\b|%|percent")
_BARE = {"volume", "the volume", "your volume", "my volume", "sound", "the sound", "sound level"}
_LOUDNESS = re.compile(r"\b(volume|loud|louder|quiet|quieter|softer|too soft|speak up)\b")
_FILLERS = re.compile(r"\b(please|ok|okay|hey|hi|um|uh|now|thanks|thank you|stack ?chan)\b")

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}  # fmt: skip
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip


@dataclass(frozen=True)
class VolumeCommand:
    # "up", "down", "set", "max", "mute", or the two answers that change nothing: "ask" (a bare
    # "volume": which way?) and "hint" (a volume remark that matched no command).
    kind: str
    level: int | None = None


def _spoken_number(words: list[str]) -> int | None:
    """The first number said in words ("sixty five", "a hundred", "one hundred"), or None."""
    for start in range(len(words)):
        total, used, seen_hundred = 0, 0, False
        for word in words[start:]:
            if word == "a" and used == 0:
                used += 1
                continue
            if word in _UNITS and not (total % 100 >= 20 and _UNITS[word] >= 10):
                total += _UNITS[word]
            elif word in _TENS:
                total += _TENS[word]
            elif word == "hundred" and not seen_hundred:
                total = max(1, total) * 100
                seen_hundred = True
            elif word == "and" and used:
                pass
            else:
                break
            used += 1
        if total or (used and words[start] == "zero"):
            return total
    return None


def _level_in(spoken: str) -> int | None:
    digits = _DIGITS.search(spoken)
    if digits:
        return int(digits.group(1))
    if _HALF.search(spoken):
        return 50
    if _QUARTER.search(spoken):
        return 25
    return _spoken_number(spoken.split())


def parse_volume_command(text: str) -> VolumeCommand | None:
    """The volume command in what the person said, or None (then it goes to the hub).

    The match searches the whole sentence, so a garbled opening word or a trailing "please" does
    not matter. A remark about the volume that matches no command still never reaches the hub as a
    question: a bare "volume" asks which way, anything else says how to ask."""
    spoken = re.sub(r"[^\w%' ]+", " ", text.lower())
    spoken = re.sub(r"\s+", " ", _FILLERS.sub(" ", spoken)).strip()
    if not spoken:
        return None
    if spoken in _BARE:
        return VolumeCommand("ask")
    mentions_volume = bool(_VOLUME.search(spoken))
    if _MAX.search(spoken):
        return VolumeCommand("max")
    if mentions_volume or "%" in spoken or "percent" in spoken:
        # "raise the volume by one" is a step, not a level.
        level = None
        if _LEVEL_CONTEXT.search(spoken) and not re.search(r"\bby\b", spoken):
            level = _level_in(spoken)
        if level is not None and not _UP.search(spoken.replace("up to", "")):
            return VolumeCommand("set", max(0, min(100, level)))
        if level is not None and re.search(r"\b(to|at) ", spoken):
            return VolumeCommand("set", max(0, min(100, level)))
    if _UP.search(spoken):
        return VolumeCommand("up")
    if _DOWN.search(spoken):
        return VolumeCommand("down")
    if _MUTE.search(spoken) and len(spoken.split()) <= 4:
        return VolumeCommand("mute")
    if mentions_volume or (_LOUDNESS.search(spoken) and len(spoken.split()) <= 6):
        return VolumeCommand("hint")
    return None


def next_level(current: int, command: VolumeCommand) -> int:
    if command.kind in {"ask", "hint"}:
        return current
    if command.kind == "up":
        return min(MAX_LEVEL, current + STEP)
    if command.kind == "down":
        return max(MIN_LEVEL, current - STEP)
    if command.kind == "max":
        return MAX_LEVEL
    if command.kind == "mute":
        return 0
    assert command.level is not None
    return max(MIN_LEVEL, min(MAX_LEVEL, command.level)) if command.level else 0


def confirmation(command: VolumeCommand, before: int, after: int) -> str:
    """One short plain line to say back (or an empty string for mute)."""
    if command.kind == "ask":
        return "Louder or quieter?"
    if command.kind == "hint":
        return "Say louder, quieter, or a number."
    if after == 0:
        return ""
    if command.kind in {"up", "max"} and after == before:
        return "That is as loud as I go."
    if command.kind == "down" and after == before:
        return "That is as quiet as I go."
    return f"Volume {after}."


class VolumeControl:
    """Reads and sets the speaker level through the device client's tool calls."""

    def __init__(
        self,
        call: Callable[[str, dict[str, object]], object],
        set_volume: Any,
        on_set: Callable[[int, VolumeCommand], None] | None = None,
    ) -> None:
        self._call = call
        self._set_volume = set_volume
        self._on_set = on_set
        self._known: int | None = None

    def current(self) -> int:
        try:
            status = self._call("self.get_device_status", {})
        except Exception:
            status = None
        level = _level_from_status(status)
        if level is not None:
            self._known = level
        return self._known if self._known is not None else DEFAULT_LEVEL

    def apply(self, command: VolumeCommand) -> tuple[int, int]:
        """Set the new level; returns (before, after). "ask" and "hint" change nothing."""
        if command.kind in {"ask", "hint"}:
            level = self._known if self._known is not None else DEFAULT_LEVEL
            return level, level
        before = self.current()
        after = next_level(before, command)
        self._set_volume(after)
        self._known = after
        if command.kind != "mute" and self._on_set is not None:
            self._on_set(after, command)
        logger.info("StackChan volume %d -> %d (%s)", before, after, command.kind)
        return before, after


def _level_from_status(status: object) -> int | None:
    if isinstance(status, str):
        import json

        try:
            status = json.loads(status)
        except ValueError:
            return None
    if not isinstance(status, Mapping):
        return None
    speaker = status.get("audio_speaker")
    if isinstance(speaker, Mapping):
        value = speaker.get("volume")
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100:
            return value
    return None
