"""Closed StackChan cue and primitive mappings, local to its body profile."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

PRIMITIVE_NAMES = (
    "listen",
    "glance",
    "tilt",
    "nod",
    "perk",
    "attend",
    "settle",
    "breathe",
    "track",
    "speak",
    "thinking",
    "offer",
    "shake",
    "stop",
)

_FACE_SET_PATH = Path(
    os.environ.get("MAIPAI_STACKCHAN_FACE_SET", Path(__file__).with_name("face_set.json"))
)
try:
    _FACE_SET_DATA = json.loads(_FACE_SET_PATH.read_text())
    SUPPORTED_FACES = frozenset(_FACE_SET_DATA["faces"])
except (OSError, ValueError, KeyError, TypeError) as exc:
    raise ValueError(f"cannot load StackChan face set from {_FACE_SET_PATH}") from exc

SUPPORTED_PRIMITIVES = set(PRIMITIVE_NAMES) - {"stop", "muted", "held"}


# The firmware release that draws the `listening` and `thinking` faces (mint skin, patch 110). An
# older unit does not know the names and would log them as unknown, so it gets `neutral` as before.
FACES_MIN_FIRMWARE = (0, 2, 66)
NEW_FACE_FALLBACK = {"listening": "neutral", "thinking": "neutral"}


def version_at_least(value: object, minimum: tuple[int, int, int]) -> bool:
    """True when a "major.minor.patch" firmware version string is at or above ``minimum``."""
    try:
        parts = tuple(int(part) for part in str(value).split(".")[:3])
        return len(parts) == 3 and parts >= minimum
    except (TypeError, ValueError):
        return False


def face_for_firmware(expression: str, firmware_version: object) -> str:
    """The face for a unit running ``firmware_version``: a newer face falls back to ``neutral``
    on firmware without it (an unknown version counts as old)."""
    if expression in NEW_FACE_FALLBACK and not version_at_least(
        firmware_version, FACES_MIN_FIRMWARE
    ):
        return NEW_FACE_FALLBACK[expression]
    return expression


@dataclass(frozen=True)
class FaceFrame:
    expression: str
    eyes: bool = True
    mouth: bool = True


@dataclass(frozen=True)
class BodyAction:
    face: str | None  # None leaves the face alone: the turn cue before this move owns it
    yaw_fraction: float = 0.0
    pitch_fraction: float = 0.0  # of the way up from level (the head only travels up)


# Turn-state cues are selected by the expression layer. Model text is never a token. The face
# carries listening and thinking (owner, 2026-11-13); the ring does not.
CUE_FACE_MAP = {
    "listening": FaceFrame(
        "listening", mouth=False
    ),  # wider eyes, closed mouth, from the wake word
    "thinking": FaceFrame("thinking", mouth=False),  # eyes up and aside, small mouth; never doubt
    "speaking": FaceFrame("neutral"),  # the firmware animates the mouth while it speaks
    "reply_mood": FaceFrame("neutral"),
}

REPLY_MOOD_FACE_MAP = {
    "neutral": "neutral",
    "happiness": "happy",
    "joy": "joy",
    "excitement": "excited",
    "surprise": "shocked",
    "love": "love",
    "affection": "love",
    "adoration": "love",
    "contentment": "content",
    "playful": "silly",
    "anger": "angry",
    "sadness": "sad",
    "fear": "worried",
    "doubt": "curious",
    "sleepiness": "sleepy",
    "wry": "wink",
}

# These deliberately small moves work within the two measured profile axes.
PRIMITIVE_BODY_MAP = {
    "listen": BodyAction("neutral", yaw_fraction=0.08),
    "glance": BodyAction("neutral", yaw_fraction=0.12),
    "tilt": BodyAction("neutral", pitch_fraction=0.08),
    "nod": BodyAction("happy", pitch_fraction=0.06),
    # The listening and thinking moves leave the face to the turn cue sent just before them (the
    # `listening` and `thinking` faces); a face of their own would paint neutral over it.
    "perk": BodyAction(None, pitch_fraction=0.10),  # lifts: pitch only goes up from level
    "attend": BodyAction(None, pitch_fraction=0.04),
    "settle": BodyAction("neutral"),
    "speak": BodyAction(None, pitch_fraction=0.04),  # the speaking cue and the reply mood own it
}

UNSUPPORTED_PRIMITIVES = {
    "breathe": (
        "StackChan has no continuously expressive axis; a static head target cannot represent "
        "breathing honestly."
    ),
    "track": (
        "StackChan tracking needs a verified camera-to-head tracking loop, which this profile "
        "does not provide."
    ),
    "thinking": "StackChan has no antennas or roll axis, which the thinking cue is made of.",
    "offer": "StackChan has no antennas, which the offer's twitch is made of.",
    "shake": "StackChan has no verified yaw sweep; a static head target cannot shake.",
    "stop": (
        "Stop is a motion-worker safety state, not an expression animation; use the worker "
        "hold path."
    ),
}

if set(PRIMITIVE_BODY_MAP) | set(UNSUPPORTED_PRIMITIVES) != set(PRIMITIVE_NAMES):
    raise RuntimeError("StackChan expression map must account for every shared primitive")

_USED_FACES = (
    {frame.expression for frame in CUE_FACE_MAP.values()}
    | {face for face in REPLY_MOOD_FACE_MAP.values() if face in SUPPORTED_FACES}
    | {action.face for action in PRIMITIVE_BODY_MAP.values() if action.face is not None}
)
for _face in sorted(_USED_FACES - SUPPORTED_FACES):
    raise ValueError(f"unsupported StackChan face: {_face}")

__all__ = [
    "BodyAction",
    "CUE_FACE_MAP",
    "FACES_MIN_FIRMWARE",
    "FaceFrame",
    "NEW_FACE_FALLBACK",
    "PRIMITIVE_BODY_MAP",
    "UNSUPPORTED_PRIMITIVES",
    "face_for_firmware",
    "version_at_least",
]
