"""Logical StackChan faces, with firmware-version fallbacks."""

from __future__ import annotations

import logging

from .expression_map import SUPPORTED_FACES, face_for_firmware, version_at_least

logger = logging.getLogger(__name__)

# The first release whose firmware draws the seven new mint faces (patch 132).
NEW_FACES_FIRMWARE: tuple[int, int, int] | None = (0, 2, 93)

# (native firmware face, fallback face already drawn by the current firmware)
FACE_VOCABULARY: dict[str, tuple[str | None, str]] = {
    "neutral": ("neutral", "neutral"),
    "happy": ("happy", "happy"),
    "joy": ("joy", "happy"),
    "content": ("content", "happy"),
    "wink": ("wink", "wink"),
    "excited": ("excited", "happy"),
    "surprised": ("surprised", "surprised"),
    "shocked": ("shocked", "surprised"),
    "curious": ("curious", "doubt"),
    "thinking": ("thinking", "thinking"),
    "listening": ("listening", "listening"),
    "love": ("love", "happy"),
    "sad": ("sad", "sad"),
    "worried": ("worried", "doubt"),
    "angry": ("angry", "angry"),
    "sleepy": ("sleepy", "sleepy"),
    "sleeping": ("sleeping", "sleeping"),
    "dizzy": (None, "doubt"),
    "silly": (None, "wink"),
}

_unknown: set[str] = set()


def resolve_face(name: str, firmware_version: object) -> str:
    """Resolve a logical face for the unit; unknown names warn once and use neutral."""
    entry = FACE_VOCABULARY.get(name)
    if entry is None:
        if name not in _unknown:
            _unknown.add(name)
            logger.warning("unknown StackChan logical face %r; using neutral", name)
        return "neutral"
    native, fallback = entry
    is_new_face = fallback != native
    if NEW_FACES_FIRMWARE is not None and version_at_least(firmware_version, NEW_FACES_FIRMWARE):
        chosen = native or fallback
    elif not is_new_face and (native in SUPPORTED_FACES or native == fallback):
        chosen = native
    else:
        chosen = fallback
    # A unit older than the listening and thinking faces gets neutral for those, as before.
    return face_for_firmware(chosen, firmware_version)


def face_for_mood(mood: str | None, *, excited: bool = False) -> str:
    """Map Home's closed mood hint, including the separate excitement signal."""
    from .expression_map import REPLY_MOOD_FACE_MAP

    if mood == "happiness" and excited:
        return "joy"
    return REPLY_MOOD_FACE_MAP.get(mood or "neutral", "neutral")


__all__ = ["FACE_VOCABULARY", "NEW_FACES_FIRMWARE", "face_for_mood", "resolve_face"]
