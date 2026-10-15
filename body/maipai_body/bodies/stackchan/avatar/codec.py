"""Binary frame codec from M5Stack StackChan's hal_ws_avatar.cpp (MIT)."""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER_SIZE = 5
MAX_FRAME_SIZE = 2**20


@dataclass(frozen=True)
class AvatarFrame:
    kind: int
    payload: bytes


def encode_frame(kind: int, payload: bytes = b"") -> bytes:
    if type(kind) is not int or not 0 <= kind <= 255:
        raise ValueError("avatar frame type must be an unsigned byte")
    if len(payload) > MAX_FRAME_SIZE:
        raise ValueError("avatar frame payload exceeds the size limit")
    return bytes((kind,)) + struct.pack(">I", len(payload)) + payload


def decode_frame(packet: bytes) -> AvatarFrame:
    if len(packet) < HEADER_SIZE:
        raise ValueError("avatar frame is shorter than its five-byte header")
    length = struct.unpack(">I", packet[1:5])[0]
    if length > MAX_FRAME_SIZE:
        raise ValueError("avatar frame payload exceeds the size limit")
    if len(packet) != HEADER_SIZE + length:
        raise ValueError("avatar frame length does not match its payload")
    return AvatarFrame(packet[0], packet[HEADER_SIZE:])
