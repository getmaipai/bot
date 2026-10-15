"""Minimal fake peer for the pinned M5Stack avatar WebSocket protocol."""

from __future__ import annotations

import json
import struct

from websockets.asyncio.client import connect


class AvatarPeer:
    def __init__(self, url: str, device_id: str, client_id: str, token: str) -> None:
        self.url = url
        self.device_id = device_id
        self.client_id = client_id
        self.token = token
        self.websocket = None

    def set_url(self, url: str) -> None:
        self.url = url

    async def connect(self):
        self.websocket = await connect(
            self.url,
            additional_headers={
                "Device-Id": self.device_id,
                "Client-Id": self.client_id,
                "Authorization": f"Bearer {self.token}",
            },
        )
        await self.websocket.send(json.dumps({"type": "hello", "msg": "Hello from StackChan!"}))
        return json.loads(await self.websocket.recv())

    async def recv_frame(self) -> bytes:
        assert self.websocket is not None
        frame = await self.websocket.recv()
        assert isinstance(frame, bytes)
        return frame

    async def send_camera_frame(self, jpeg: bytes) -> None:
        assert self.websocket is not None
        await self.websocket.send(bytes((0x01,)) + struct.pack(">I", len(jpeg)) + jpeg)

    async def close(self) -> None:
        if self.websocket is not None:
            await self.websocket.close()
