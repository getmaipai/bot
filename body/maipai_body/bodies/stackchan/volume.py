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

_UP = re.compile(
    r"\b(louder|turn (it |the volume |the sound )?up|volume up|raise the volume|"
    r"increase the volume|speak up|talk louder|a bit louder|too quiet|can'?t hear you)\b"
)
_DOWN = re.compile(
    r"\b(quieter|softer|turn (it |the volume |the sound )?down|volume down|lower the volume|"
    r"decrease the volume|talk quieter|too loud|not so loud|a bit quieter)\b"
)
_SET = re.compile(
    r"\b(?:set |make |put )?(?:the )?volume (?:to|at) (\d{1,3})(?: ?(?:percent|%))?\b"
)
_MAX = re.compile(r"\b(max(imum)? volume|full volume|as loud as you can)\b")
_MUTE = re.compile(r"\b(mute|be quiet|silence)\b")


@dataclass(frozen=True)
class VolumeCommand:
    kind: str  # "up", "down", "set", "max" or "mute"
    level: int | None = None


def parse_volume_command(text: str) -> VolumeCommand | None:
    """The volume command in what the person said, or None (then it goes to the hub)."""
    spoken = re.sub(r"[^\w%' ]+", " ", text.lower()).strip()
    if not spoken:
        return None
    match = _SET.search(spoken)
    if match:
        return VolumeCommand("set", max(0, min(100, int(match.group(1)))))
    if _MAX.search(spoken):
        return VolumeCommand("max")
    if _UP.search(spoken):
        return VolumeCommand("up")
    if _DOWN.search(spoken):
        return VolumeCommand("down")
    if _MUTE.search(spoken) and len(spoken.split()) <= 4:
        return VolumeCommand("mute")
    return None


def next_level(current: int, command: VolumeCommand) -> int:
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
    if after == 0:
        return ""
    if command.kind in {"up", "max"} and after == before:
        return "That is as loud as I go."
    if command.kind == "down" and after == before:
        return "That is as quiet as I go."
    return f"Volume {after}."


class VolumeControl:
    """Reads and sets the speaker level through the device client's tool calls."""

    def __init__(self, call: Callable[[str, dict[str, object]], object], set_volume: Any) -> None:
        self._call = call
        self._set_volume = set_volume
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
        """Set the new level; returns (before, after)."""
        before = self.current()
        after = next_level(before, command)
        self._set_volume(after)
        self._known = after
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
