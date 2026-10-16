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


@dataclass(frozen=True)
class FaceFrame:
    expression: str
    eyes: bool = True
    mouth: bool = True


@dataclass(frozen=True)
class BodyAction:
    face: str
    yaw_fraction: float = 0.0
    pitch_fraction: float = 0.0
    led: tuple[int, int, int] = (0, 0, 0)


# Turn-state cues are selected by the expression layer. Model text is never a token.
CUE_FACE_MAP = {
    "listening": FaceFrame("neutral", mouth=False),
    "thinking": FaceFrame("doubt", mouth=False),
    "speaking": FaceFrame("happy"),
    "reply_mood": FaceFrame("neutral"),
}

REPLY_MOOD_FACE_MAP = {
    "neutral": "neutral",
    "happiness": "happy",
    "anger": "angry",
    "sadness": "sad",
    "fear": "doubt",
    "doubt": "doubt",
    "sleepiness": "sleepy",
    "wry": "doubt",
}

# These deliberately small moves work within the two measured profile axes.
PRIMITIVE_BODY_MAP = {
    "listen": BodyAction("neutral", yaw_fraction=0.08, led=(0, 45, 80)),
    "glance": BodyAction("doubt", yaw_fraction=0.12),
    "tilt": BodyAction("doubt", pitch_fraction=0.08),
    "nod": BodyAction("happy", pitch_fraction=0.06),
    "perk": BodyAction("happy", pitch_fraction=-0.06, led=(0, 70, 20)),
    "attend": BodyAction("sad", pitch_fraction=0.04, led=(30, 15, 60)),
    "settle": BodyAction("neutral"),
    "speak": BodyAction("happy", pitch_fraction=-0.03),
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
    | set(REPLY_MOOD_FACE_MAP.values())
    | {action.face for action in PRIMITIVE_BODY_MAP.values()}
)
for _face in sorted(_USED_FACES - SUPPORTED_FACES):
    raise ValueError(f"unsupported StackChan face: {_face}")

__all__ = [
    "BodyAction",
    "CUE_FACE_MAP",
    "FaceFrame",
    "PRIMITIVE_BODY_MAP",
    "UNSUPPORTED_PRIMITIVES",
]
