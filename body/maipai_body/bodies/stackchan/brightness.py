"""Spoken screen brightness for the StackChan, answered on the robot without asking the hub.

"Brightness 50", "make it dimmer", "it's too dark" and "full brightness" change the screen through
the firmware's ``self.screen.set_brightness`` tool. Same matcher style as ``volume.py``, with one
difference: the level never goes below ``MIN_LEVEL``, so no phrase can switch the screen off by
accident (a dark screen with no touch wake looks like a dead robot).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from maipai_body.bodies.stackchan.volume import _FILLERS, _level_in

logger = logging.getLogger("maipai_body.bodies.stackchan.brightness")

MIN_LEVEL = 10
MAX_LEVEL = 100
STEP = 20
DEFAULT_LEVEL = 100

_NOUN = re.compile(r"\b(brightness|screen brightness|backlight)\b")
_THE = r"(?:(?:the|your|my|that|this) )?"
_UP = re.compile(
    r"\b(brighter|"
    rf"(?:raise|increase|turn up|bump up|boost|crank up|up) {_THE}(?:brightness|backlight)|"
    rf"(?:brighten|light up) {_THE}(?:screen|display|it)|brightness up|more brightness|"
    r"(?:too|so) (?:dark|dim)|"
    r"(?:can'?t|cannot|can not|hard to) see (?:the |your )?(?:screen|display))\b"
)
_DOWN = re.compile(
    r"\b(dimmer|darker|"
    rf"(?:lower|decrease|reduce|turn down|bring down|drop|down) {_THE}(?:brightness|backlight)|"
    r"dim (?:the |your |my )?(?:screen|display|it|yourself|face)|"
    r"brightness down|less brightness|"
    r"(?:too|so|way too) bright|too glaring|hurts my eyes)\b"
)
_MAX = re.compile(
    r"\b(max(?:imum)? brightness|full brightness|brightness (?:to |at )?(?:max|maximum|full)|"
    r"as bright as you can)\b"
)
_SCREEN_OFF = re.compile(r"\b(screen|display) off\b|\bturn off (?:the |your )?(?:screen|display)\b")
_LEVEL_CONTEXT = re.compile(r"\b(brightness|backlight|set|make|put|turn)\b|%|percent")
_BARE = {"brightness", "the brightness", "your brightness", "screen brightness", "backlight"}


@dataclass(frozen=True)
class BrightnessCommand:
    # "up", "down", "set", "max", or the answers that change nothing: "ask" (a bare
    # "brightness": which way?), "hint" (a brightness remark that matched no command) and
    # "off" (a screen-off request, refused with a line saying how to dim instead).
    kind: str
    level: int | None = None


def parse_brightness_command(text: str) -> BrightnessCommand | None:
    """The brightness command in what the person said, or None (then it goes on to the hub)."""
    spoken = re.sub(r"[^\w%' ]+", " ", text.lower())
    spoken = re.sub(r"\s+", " ", _FILLERS.sub(" ", spoken)).strip()
    if not spoken:
        return None
    if spoken in _BARE:
        return BrightnessCommand("ask")
    if re.search(r"\bvolume\b", spoken):
        return None  # the volume matcher's sentence
    if _SCREEN_OFF.search(spoken):
        return BrightnessCommand("off")
    if _MAX.search(spoken):
        return BrightnessCommand("max")
    mentions = bool(_NOUN.search(spoken))
    if mentions or (("%" in spoken or "percent" in spoken) and "screen" in spoken):
        level = None
        if _LEVEL_CONTEXT.search(spoken) and not re.search(r"\bby\b", spoken):
            level = _level_in(spoken)
        if level is not None and not _UP.search(spoken.replace("up to", "")):
            return BrightnessCommand("set", max(0, min(100, level)))
        if level is not None and re.search(r"\b(to|at) ", spoken):
            return BrightnessCommand("set", max(0, min(100, level)))
    short = len(spoken.split()) <= 8
    if _UP.search(spoken) and (short or mentions):
        return BrightnessCommand("up")
    if _DOWN.search(spoken) and (short or mentions):
        return BrightnessCommand("down")
    return BrightnessCommand("hint") if mentions else None


def next_level(current: int, command: BrightnessCommand) -> int:
    if command.kind in {"ask", "hint", "off"}:
        return current
    if command.kind == "up":
        return min(MAX_LEVEL, current + STEP)
    if command.kind == "down":
        return max(MIN_LEVEL, current - STEP)
    if command.kind == "max":
        return MAX_LEVEL
    assert command.level is not None
    return max(MIN_LEVEL, min(MAX_LEVEL, command.level))


def confirmation(command: BrightnessCommand, before: int, after: int) -> str:
    """One short plain line to say back."""
    if command.kind == "ask":
        return "Brighter or dimmer?"
    if command.kind == "hint":
        return "Say brighter, dimmer, or a number."
    if command.kind == "off":
        return "I keep the screen on so you can find me. Say dimmer, or a number."
    if command.kind in {"up", "max"} and after == before:
        return "That is as bright as I go."
    if command.kind == "down" and after == before:
        return "That is as dim as I go."
    return f"Brightness {after}."


class BrightnessControl:
    """Reads and sets the screen level through the night controller (which owns day and night)."""

    def __init__(self, current: Callable[[], int], apply: Callable[[int], None]) -> None:
        self._current = current
        self._apply = apply

    def apply(self, command: BrightnessCommand) -> tuple[int, int]:
        """Set the new level; returns (before, after). "ask", "hint" and "off" change nothing."""
        before = self._current()
        after = next_level(before, command)
        if after != before:
            self._apply(after)
        logger.info("StackChan brightness %d -> %d (%s)", before, after, command.kind)
        return before, after
