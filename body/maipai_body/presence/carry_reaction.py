"""MOVE-CARRY-01c: what the body shows and says when it is lifted.

The setting governs only the look and the line; the holds of
``motion_state`` are the motion floor and are never configurable.

The line is a physical-safety rule, not a content rule (the EYES-04
precedent): a voice from a body in the air can startle a small child, so
it plays only when every presence entry is a known adult. A child, a teen,
an unknown person, an empty list or no presence information at all gives
the silent look. There is no setting for this and no teen opt-out.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from maipai_body.speech.offline_clips import CARRY_LINES as CARRY_LINES  # noqa: PLC0414


class CarryReaction(StrEnum):
    OFF = "off"
    LOOK = "look"
    LOOK_AND_LINE = "look_and_line"


DEFAULT_CARRY_REACTION = CarryReaction.LOOK

PresenceKind = Literal["adult", "teen", "child", "unknown"]
_KINDS = ("adult", "teen", "child", "unknown")


@dataclass(frozen=True)
class PresenceEntry:
    """One person the body believes is present, by age band only."""

    kind: PresenceKind

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"presence kind must be one of {_KINDS}, got {self.kind!r}")


def line_allowed(entries: Sequence[PresenceEntry] | None) -> bool:
    """True only when someone is present and every entry is a known adult."""
    if not entries:
        return False
    return all(entry.kind == "adult" for entry in entries)
