"""Authenticated M5 StackChan avatar WebSocket channel."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from ..xiaozhi.pairing import PairingStore
from .codec import MAX_FRAME_SIZE, decode_frame, encode_frame

LOG = logging.getLogger(__name__)
CONTROL_AVATAR = 0x03
CONTROL_MOTION = 0x04
CAMERA_FRAME = 0x01
MAX_CAMERA_FRAME_SIZE = 2 * 1024 * 1024
HELLO_TIMEOUT_S = 10.0
MAX_HELLO_SIZE = 4096

# M5's app_avatar passes this object directly to updateAvatarFromJson.
# Keep the expression table closed and local; model text never becomes a face token.
EXPRESSIONS = {
    "neutral": "neutral",
    "happy": "happy",
    "joy": "happy",
    "angry": "angry",
    "sad": "sad",
    "doubt": "doubt",
    "sleepy": "sleepy",
}
_EYE_WEIGHTS = {"neutral": 100, "happy": 72, "angry": 70, "sad": 70, "doubt": 75, "sleepy": 35}
_EYE_ROTATIONS = {"neutral": 0, "happy": 1550, "angry": 450, "sad": -400, "doubt": 0, "sleepy": -50}


def control_avatar(expression: str, *, eyes: bool = True, mouth: bool = True) -> bytes:
    try:
        emotion = EXPRESSIONS[expression]
    except KeyError as exc:
        raise ValueError(f"unsupported StackChan expression {expression!r}") from exc
    weight = _EYE_WEIGHTS[emotion]
    rotation = _EYE_ROTATIONS[emotion]
    eye = {"weight": weight, "rotation": rotation}
    mouth_feature = {"weight": 35} if mouth else {"weight": 0}
    payload = {
        "leftEye": eye if eyes else {"size": -100},
        "rightEye": {"weight": weight, "rotation": -rotation} if eyes else {"size": -100},
        "mouth": mouth_feature,
    }
    return encode_frame(
        CONTROL_AVATAR,
        json.dumps(payload, separators=(",", ":")).encode(),
    )


class AvatarServer:
    """Keeps the device-initiated avatar channel open and replaces stale sessions."""

    def __init__(self, pairing: PairingStore, *, idle_timeout: float = 30.0) -> None:
        self.pairing = pairing
        self.idle_timeout = idle_timeout
        self.estop_engaged = False
        self._server: Any = None
        self._sessions: dict[str, ServerConnection] = {}
        self.on_camera_frame: Any = None
        self._camera_frames: dict[str, tuple[bytes, float]] = {}
        self._camera_events: dict[str, asyncio.Event] = {}
        self._camera_disconnects: dict[str, asyncio.Event] = {}
        self._camera_ready = threading.Condition()
        self.camera_frame_count = 0

    async def start(self, host: str = "127.0.0.1", port: int = 8766, **kwargs: Any) -> None:
        self._server = await serve(
            self.handle,
            host,
            port,
            max_size=MAX_FRAME_SIZE + 5,
            ping_interval=20,
            ping_timeout=20,
            **kwargs,
        )

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def handle(self, websocket: ServerConnection) -> None:
        request = websocket.request
        if request.path != "/stackChan/ws?deviceType=StackChan":
            await websocket.close(1008, "Use /stackChan/ws?deviceType=StackChan.")
            return
        headers = request.headers
        device_id = headers.get("Device-Id", "")
        client_id = headers.get("Client-Id", "")
        authorization = headers.get("Authorization", "")
        token = authorization[7:] if authorization.startswith("Bearer ") else None
        if not self.pairing.authorize(device_id, client_id, token):
            try:
                self.pairing.request(device_id, client_id)
            except ValueError:
                await websocket.close(1008, "Valid Device-Id and Client-Id headers are required.")
                return
            await websocket.close(1008, "Device is not approved; approve its Device-Id first.")
            return

        stale = self._sessions.get(device_id)
        if stale is not None:
            asyncio.create_task(self._close_stale(stale))
        self._sessions[device_id] = websocket
        try:
            try:
                hello = await asyncio.wait_for(websocket.recv(), HELLO_TIMEOUT_S)
            except TimeoutError:
                await websocket.close(1002, "Send the StackChan avatar hello after connecting.")
                return
            if not isinstance(hello, str) or len(hello) > MAX_HELLO_SIZE:
                await websocket.close(1002, "Avatar hello must be a small JSON text frame.")
                return
            try:
                data = json.loads(hello)
            except json.JSONDecodeError:
                await websocket.close(1002, "Malformed JSON avatar hello.")
                return
            if not isinstance(data, dict) or data.get("type") != "hello":
                await websocket.close(1002, "Expected the StackChan avatar hello frame.")
                return
            await websocket.send(json.dumps({"type": "hello", "session_id": uuid.uuid4().hex}))
            async for message in websocket:
                if not self.pairing.authorize(device_id, client_id, token):
                    await websocket.close(1008, "Pairing was revoked; reconnect after approval.")
                    return
                if not isinstance(message, bytes):
                    continue
                try:
                    frame = decode_frame(message)
                except ValueError as exc:
                    await websocket.close(1002, str(exc))
                    return
                if frame.kind == CONTROL_MOTION and self.estop_engaged:
                    LOG.warning("blocked avatar motion frame while software estop is engaged")
                elif frame.kind == CAMERA_FRAME:
                    if not _valid_jpeg(frame.payload):
                        LOG.warning("discarded malformed StackChan camera frame")
                        continue
                    self._camera_frames[device_id] = (frame.payload, time.monotonic())
                    self.camera_frame_count = len(self._camera_frames)
                    with self._camera_ready:
                        self._camera_ready.notify_all()
                    self._camera_events.setdefault(device_id, asyncio.Event()).set()
                    if self.on_camera_frame is not None:
                        try:
                            result = self.on_camera_frame(device_id, frame.payload)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception:
                            LOG.debug("camera frame callback failed", exc_info=True)
        except ConnectionClosed:
            pass
        except Exception:
            LOG.debug("avatar session ended", exc_info=True)
        finally:
            if self._sessions.get(device_id) is websocket:
                self._sessions.pop(device_id, None)
                self.clear_camera_frame(device_id)
                self._camera_disconnects.setdefault(device_id, asyncio.Event()).set()
                event = self._camera_events.get(device_id)
                if event is not None:
                    event.clear()

    async def wait_for_camera_frame(self, device_id: str) -> None:
        event = self._camera_events.setdefault(device_id, asyncio.Event())
        if device_id not in self._camera_frames:
            await asyncio.wait_for(event.wait(), 1.0)

    async def wait_for_camera_disconnect(self, device_id: str) -> None:
        event = self._camera_disconnects.setdefault(device_id, asyncio.Event())
        if device_id in self._sessions:
            await asyncio.wait_for(event.wait(), 1.0)

    def pop_camera_frame(self, device_id: str, *, max_age_s: float = 0.5) -> bytes | None:
        item = self._camera_frames.pop(device_id, None)
        self.camera_frame_count = len(self._camera_frames)
        if item is None or time.monotonic() - item[1] > max_age_s:
            return None
        return item[0]

    def clear_camera_frame(self, device_id: str) -> None:
        """Drop the buffered JPEG for one device, including at disconnect."""
        self._camera_frames.pop(device_id, None)
        self.camera_frame_count = len(self._camera_frames)
        event = self._camera_events.get(device_id)
        if event is not None:
            event.clear()
        with self._camera_ready:
            self._camera_ready.notify_all()

    def wait_camera_device_frame(self, device_id: str, *, timeout: float) -> bool:
        """Wait from a worker thread for one authenticated device's frame."""
        deadline = time.monotonic() + timeout
        with self._camera_ready:
            while device_id not in self._camera_frames:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._camera_ready.wait(remaining)
            return True

    async def _close_stale(self, websocket: ServerConnection) -> None:
        await websocket.close(1012, "A replacement avatar session connected.")

    async def send_expression(
        self, device_id: str, expression: str, *, eyes: bool = True, mouth: bool = True
    ) -> None:
        websocket = self._sessions.get(device_id)
        if websocket is None:
            raise ConnectionError("StackChan avatar channel is not connected.")
        if not self.pairing.authorize(
            device_id,
            websocket.request.headers.get("Client-Id", ""),
            _bearer(websocket.request.headers.get("Authorization", "")),
        ):
            await websocket.close(1008, "Pairing was revoked; reconnect after approval.")
            raise PermissionError("StackChan pairing was revoked.")
        await websocket.send(control_avatar(expression, eyes=eyes, mouth=mouth))

    async def send_frame(self, device_id: str, frame: bytes) -> None:
        websocket = self._sessions.get(device_id)
        if websocket is None:
            raise ConnectionError(
                "StackChan avatar channel is not connected. Reconnect the device and retry."
            )
        await websocket.send(frame)


def _bearer(value: str) -> str | None:
    return value[7:] if value.startswith("Bearer ") else None


def _valid_jpeg(payload: bytes) -> bool:
    return (
        4 <= len(payload) <= MAX_CAMERA_FRAME_SIZE
        and payload.startswith(b"\xff\xd8")
        and payload.endswith(b"\xff\xd9")
    )
