"""StackChan avatar-channel binary frame codec, independent of any server."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path


class AvatarCommand(IntEnum):
    START_CAMERA_STREAM = 0x05


_FACE_SET = json.loads(Path(__file__).with_name("face_set.json").read_text())
SUPPORTED_FACES = frozenset(_FACE_SET["faces"])


@dataclass(frozen=True)
class AvatarFrame:
    command: int
    payload: bytes = b""


def encode_frame(command: int | AvatarCommand, payload: bytes = b"") -> bytes:
    """Encode an M5 avatar frame using its 0xAA55/length/command envelope."""
    if not 0 <= int(command) <= 255:
        raise ValueError("avatar command must fit in one byte")
    if len(payload) > 65535:
        raise ValueError("avatar payload exceeds the two-byte frame length")
    return b"\xaa\x55" + len(payload).to_bytes(2, "big") + bytes([int(command)]) + payload


def encode_face(expression: str, payload: bytes = b"") -> bytes:
    """Validate a face token before encoding its ControlAvatar payload."""
    if expression not in SUPPORTED_FACES:
        raise ValueError(f"unsupported StackChan face: {expression}")
    return encode_frame(0x03, payload)


def decode_frame(data: bytes) -> AvatarFrame:
    if len(data) < 5 or data[:2] != b"\xaa\x55":
        raise ValueError("invalid avatar frame header")
    size = int.from_bytes(data[2:4], "big")
    if len(data) != size + 5:
        raise ValueError("avatar frame length does not match payload")
    return AvatarFrame(data[4], data[5:])


def start_camera_stream() -> bytes:
    return encode_frame(AvatarCommand.START_CAMERA_STREAM)


def stop_camera_stream() -> bytes:
    return encode_frame(AvatarCommand.START_CAMERA_STREAM, b"\x00")
