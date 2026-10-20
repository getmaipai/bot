"""Small xiaozhi WebSocket endpoint for the StackChan voice and tool channel."""

from __future__ import annotations

import asyncio
import concurrent.futures
import itertools
import json
import logging
import ssl
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from aiohttp import web
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from maipai_body.bodies.stackchan.avatar_frames import AvatarCommand, decode_frame
from maipai_body.hal.errors import BodyLost, EstopEngaged, NotSupported, OutOfEnvelope

from .pairing import PairingStore

LOG = logging.getLogger(__name__)
# Time the firmware needs to enter its speaking state after tts start.
SPEAK_SETTLE_S = 0.15
# Spacing between prebuffered frames. The robot has 9 Wi-Fi receive buffers and a 3-packet
# block-ack window; 30 frames sent back to back overflowed them, and the lost packet stalled
# the stream for a 1.5 s retransmit (gap heard mid-line on the 2026-10-20 bench).
PREBUFFER_GAP_S = 0.015
# Face names the StackChan display's SetEmotion accepts (stackchan_display.cc).
FIRMWARE_EMOTIONS = {
    "neutral": "neutral",
    "happy": "happy",
    "angry": "angry",
    "sad": "sad",
    "doubt": "doubtful",
    "sleepy": "sleepy",
    "surprised": "surprised",
    "wink": "winking",
}
MAX_EARLY_DEVICE_REPLIES = 32


class XiaozhiDeviceClient:
    """Synchronous Robot seam that sends MCP tool calls to the active device."""

    def __init__(self, server: XiaozhiServer, *, timeout: float = 5.0) -> None:
        self.server = server
        self.timeout = timeout

    def get_head_angles(self) -> dict[str, int]:
        result = self._call("self.robot.get_head_angles", {})
        if (
            not isinstance(result, dict)
            or type(result.get("yaw")) is not int
            or type(result.get("pitch")) is not int
        ):
            raise BodyLost(
                "StackChan returned invalid head angles. Check firmware compatibility and "
                "reconnect."
            )
        return result

    def set_head_angles(self, yaw: int | None, pitch: int | None, speed: int) -> object:
        return self._call(
            "self.robot.set_head_angles",
            {
                "yaw": yaw if yaw is not None else -9999,
                "pitch": pitch if pitch is not None else -9999,
                "speed": speed,
            },
        )

    def set_led_color(self, red: int, green: int, blue: int) -> object:
        return self._call("self.robot.set_led_color", {"red": red, "green": green, "blue": blue})

    def set_volume(self, volume: int) -> object:
        return self._call("self.audio_speaker.set_volume", {"volume": volume})

    def set_brightness(self, brightness: int) -> object:
        # Upstream xiaozhi tool (mcp_server.cc), present because the board has a backlight.
        return self._call("self.screen.set_brightness", {"brightness": brightness})

    def set_face_background(self, palette: str, night: bool) -> object:
        return self._call("self.screen.set_face_background", {"palette": palette, "night": night})

    def set_idle_motion(self, enabled: bool) -> object:
        return self._call("self.robot.set_idle_motion", {"enabled": enabled})

    def get_ambient_light(self) -> float | None:
        try:
            result = self._call("self.screen.get_ambient_light", {})
        except Exception:
            return None
        if isinstance(result, dict) and isinstance(result.get("lux"), (int, float)):
            return float(result["lux"])
        return None

    def get_battery_status(self) -> dict[str, object]:
        """Read battery status using the firmware's read-only MCP tool."""
        result = self._call("self.battery.get_status", {})
        if (
            not isinstance(result, dict)
            or type(result.get("percent")) is not int
            or not 0 <= result["percent"] <= 100
            or type(result.get("charging")) is not bool
        ):
            raise BodyLost(
                "StackChan returned invalid battery status. Check firmware compatibility and "
                "reconnect."
            )
        return result

    def push_action(self, action: str, arguments: dict[str, object]) -> object:
        names = {
            "create_reminder": "self.robot.create_reminder",
            "get_reminders": "self.robot.get_reminders",
            "stop_reminder": "self.robot.stop_reminder",
            "listen_window": "self.audio.listen",
            "speak": "self.audio.notify",
            "alert": "self.audio.alert",
        }
        name = names.get(action)
        if name is None:
            raise NotSupported(f"Unknown StackChan push action '{action}'")
        return self._call(name, arguments)

    def device_supports(self, feature: str) -> bool:
        return self.server.device_supports(feature)

    def create_notification_audio(self, message: object) -> str:
        return self.server.create_notification_audio(message)

    def notify(self, audio_url: str) -> object:
        try:
            return asyncio.run_coroutine_threadsafe(
                self.server.send_notify(audio_url), self.server._loop
            ).result(timeout=self.timeout)
        except Exception as exc:
            if isinstance(exc, NotSupported):
                raise
            raise BodyLost("StackChan notify push failed; reconnect and retry.") from exc

    def take_photo(self) -> bytes | None:
        return self._call("self.camera.take_photo", {"question": "Describe what you see."})

    def send_avatar_frame(self, frame: bytes) -> object:
        try:
            return asyncio.run_coroutine_threadsafe(
                self.server.send_expression_frame(frame), self.server._loop
            ).result(timeout=self.timeout)
        except Exception as exc:
            raise BodyLost(
                "StackChan camera stream command failed. Reconnect it and retry."
            ) from exc

    def cancel_pending(self) -> None:
        self.server.cancel_device_calls("self.robot.set_head_angles")

    def _call(self, name: str, arguments: dict[str, object]) -> object:
        try:
            return self.server.call_device_tool(name, arguments, timeout=self.timeout)
        except (BodyLost, EstopEngaged, NotSupported, OutOfEnvelope):
            raise
        except concurrent.futures.CancelledError as exc:
            raise EstopEngaged(
                "Robot command was cancelled by the software stop. Release it before retrying."
            ) from exc
        except RuntimeError as exc:
            message = str(exc)
            normalized = message.lower()
            if any(
                term in normalized for term in ("out of range", "outside the limit", "envelope")
            ):
                raise OutOfEnvelope(message) from exc
            if any(term in normalized for term in ("not supported", "unsupported", "unknown tool")):
                part, capability = self._tool_contract(name)
                raise NotSupported(
                    f"StackChan does not support {name}: {message}",
                    part=part,
                    capability=capability,
                    fix="Use a command supported by this StackChan profile.",
                ) from exc
            raise BodyLost(
                f"StackChan did not complete {name}. Check its connection and retry."
            ) from exc
        except (ConnectionError, TimeoutError, PermissionError, ValueError) as exc:
            raise BodyLost(f"StackChan did not complete {name}. Reconnect it and retry.") from exc
        except Exception as exc:
            raise BodyLost(
                f"StackChan did not complete {name}. Check its connection and retry."
            ) from exc

    @staticmethod
    def _tool_contract(name: str) -> tuple[str, str]:
        if name.startswith("self.robot.set_head_angles") or name.startswith(
            "self.robot.get_head_angles"
        ):
            return "head", "head_pan_tilt"
        if name.startswith("self.robot.set_led_color"):
            return "leds", "light_ring"
        if name.startswith("self.audio_speaker.set_volume"):
            return "audio", "speaker"
        return "", ""


class RobotAdapter(Protocol):
    """Minimal body seam. A later StackChan profile adapts the shared robot object."""

    async def set_head_angles(
        self, yaw: int | None, pitch: int | None, speed: int = 150
    ) -> object: ...

    async def get_head_angles(self) -> object: ...

    async def set_led_color(self, red: int, green: int, blue: int) -> object: ...

    async def set_volume(self, volume: int) -> object: ...


AudioHandler = Callable[[str, bytes], Awaitable[None]]


class XiaozhiServer:
    def __init__(
        self,
        pairing: PairingStore,
        robot: RobotAdapter | None,
        audio_handler: AudioHandler | None = None,
        *,
        version: str = "1",
        server_name: str = "MaiPai Bot",
        idle_timeout: float = 30.0,
        vision_host: str = "127.0.0.1",
        vision_port: int = 8767,
        max_photo_bytes: int = 2 * 1024 * 1024,
        advertised_vision_url: str | None = None,
        notification_audio_handler: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        self.pairing = pairing
        self.robot = robot
        self.audio_handler = audio_handler
        self.turn_handler: Callable[[str, str, str], Awaitable[None]] | None = None
        self.version = version
        self.server_name = server_name
        self.idle_timeout = idle_timeout
        self.vision_host = vision_host
        self.vision_port = vision_port
        self.max_photo_bytes = max_photo_bytes
        self.advertised_vision_url = advertised_vision_url
        self.notification_audio_handler = notification_audio_handler
        self._vision_runner: web.AppRunner | None = None
        self._vision_site: web.TCPSite | None = None
        self._photos: dict[str, bytes] = {}
        self._photo_waiters: dict[str, asyncio.Future[bytes]] = {}
        self._camera_streaming: set[str] = set()
        self._avatar_frame_sender: Callable[[str, bytes], Awaitable[None]] | None = None
        self._server: Any = None
        self._sessions: dict[str, ServerConnection] = {}
        self._session_ids: dict[str, str] = {}
        self._session_features: dict[str, dict[str, Any]] = {}
        self._session_credentials: dict[str, tuple[str, str]] = {}
        self._pending_device_calls: dict[str, tuple[asyncio.Future[object], str, str]] = {}
        self._early_device_replies: dict[str, dict[str, Any]] = {}
        self._device_call_deadlines: dict[str, float] = {}
        self._next_device_request_id = itertools.count(1)
        self._speaking: set[str] = set()
        self._source_requests: dict[str, list[float]] = {}
        self._notification_audio: dict[tuple[str, str], bytes] = {}
        self._session_ready = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        ssl: ssl.SSLContext | None = None,
    ) -> None:
        self._loop = asyncio.get_running_loop()
        self._server = await serve(
            self.handle,
            host,
            port,
            max_size=2**20,
            ping_interval=20,
            ping_timeout=20,
            ssl=ssl,
        )
        app = web.Application(client_max_size=self.max_photo_bytes)
        app.router.add_post("/vision/{device_id}", self._receive_photo)
        app.router.add_get("/notify/{device_id}/{audio_id}.ogg", self._serve_notify_audio)
        self._vision_runner = web.AppRunner(app)
        await self._vision_runner.setup()
        self._vision_site = web.TCPSite(self._vision_runner, self.vision_host, self.vision_port)
        await self._vision_site.start()
        if self.vision_port == 0 and self._vision_site._server is not None:
            sockets = self._vision_site._server.sockets
            if sockets:
                self.vision_port = int(sockets[0].getsockname()[1])

    async def close(self) -> None:
        for device_id in tuple(self._camera_streaming):
            await self._stop_camera(device_id)
        if self._vision_runner is not None:
            await self._vision_runner.cleanup()
            self._vision_runner = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def handle(self, websocket: ServerConnection) -> None:
        self._loop = asyncio.get_running_loop()
        device_id = websocket.request.headers.get("Device-Id", "")
        client_id = websocket.request.headers.get("Client-Id", "")
        protocol_version = websocket.request.headers.get("Protocol-Version", "1")
        auth = websocket.request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else None
        if not self.pairing.authorize(device_id, client_id, token):
            try:
                source = websocket.remote_address[0] if websocket.remote_address else "unknown"
                if not self.pairing.recognizes_device(device_id, client_id) and not (
                    self._allow_pairing_request(source)
                ):
                    await websocket.close(
                        code=1013,
                        reason=(
                            "Too many pairing requests from this address. Wait 10 minutes "
                            "and retry."
                        ),
                    )
                    return
                self.pairing.request(device_id, client_id)
            except ValueError:
                await websocket.close(
                    code=1008,
                    reason="Missing valid Device-Id or Client-Id. Set both headers and reconnect.",
                )
                return
            await websocket.close(
                code=1008,
                reason=(
                    "Device is not approved. Ask a Bot admin to "
                    "approve this Device-Id in the dashboard, then "
                    "provision its token file."
                ),
            )
            return

        if protocol_version != "1":
            await websocket.close(
                code=1002,
                reason="Protocol-Version is unsupported. Set it to 1 in NVS and reconnect.",
            )
            return

        session_id = uuid.uuid4().hex
        stale = self._sessions.get(device_id)
        if stale is not None:
            asyncio.create_task(self._close_stale_session(stale))
        self._sessions[device_id] = websocket
        self._session_ids[device_id] = session_id
        self._session_credentials[device_id] = (client_id, token or "")
        bind_camera = getattr(self.robot, "bind_avatar_camera", None)
        if callable(bind_camera) and self._avatar_frame_sender is not None:
            avatar_server = getattr(self._avatar_frame_sender, "__self__", None)
            if avatar_server is not None:
                bind_camera(avatar_server, device_id)
        self._session_ready.set()
        hello_received = False
        try:
            while True:
                try:
                    if hello_received:
                        message = await websocket.recv()
                    else:
                        message = await asyncio.wait_for(
                            websocket.recv(), timeout=self.idle_timeout
                        )
                except TimeoutError:
                    await websocket.close(
                        code=1001,
                        reason=(
                            "No xiaozhi frame arrived before the idle timeout. Send a hello "
                            "frame, then reconnect."
                        ),
                    )
                    break
                if not self._session_authorized(device_id):
                    await websocket.close(
                        code=1008,
                        reason=(
                            "This pairing was revoked. Ask an admin to approve it again, "
                            "then provision a new token."
                        ),
                    )
                    break
                if isinstance(message, bytes):
                    if device_id in self._camera_streaming:
                        self._photos[device_id] = message
                    elif self.audio_handler:
                        await self.audio_handler(session_id, message)
                    continue
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    await self._send_error(
                        websocket,
                        session_id,
                        -32700,
                        "Invalid JSON. Send a xiaozhi JSON text frame.",
                    )
                    continue
                kind = data.get("type")
                if kind == "hello":
                    if hello_received:
                        await self._send_error(
                            websocket,
                            session_id,
                            -32600,
                            "Repeated hello frame for this session. Continue using the active "
                            "session, or reconnect the device to start a new one.",
                        )
                        continue
                    hello_received = True
                    features = data.get("features", {})
                    self._session_features[device_id] = (
                        dict(features) if isinstance(features, dict) else {}
                    )
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "hello",
                                "version": 1,
                                "transport": "websocket",
                                "session_id": session_id,
                                "audio_params": {
                                    "format": "opus",
                                    "sample_rate": 24000,
                                    "channels": 1,
                                    "frame_duration": 60,
                                },
                            }
                        )
                    )
                elif kind == "listen":
                    state = data.get("state")
                    if state in {"start", "detect", "stop"} and self.turn_handler is not None:
                        await self.turn_handler(session_id, device_id, state)
                    if state in {"start", "detect"}:
                        if data.get("mode") == "realtime":
                            await self._json(websocket, session_id, "tts", {"state": "start"})
                    elif state == "stop":
                        await self._json(websocket, session_id, "tts", {"state": "stop"})
                elif kind == "abort":
                    self._speaking.discard(device_id)
                    if self.turn_handler is not None:
                        await self.turn_handler(session_id, device_id, "abort")
                    await self._json(websocket, session_id, "tts", {"state": "stop"})
                elif kind == "mcp":
                    await self._mcp(websocket, session_id, data.get("payload", {}))
                else:
                    await self._send_error(
                        websocket,
                        session_id,
                        -32600,
                        "Unsupported message type. Send hello, listen, abort, or mcp.",
                    )
        except ConnectionClosedError as exc:
            if any(close is not None and close.code == 1009 for close in (exc.rcvd, exc.sent)):
                LOG.warning(
                    "StackChan sent a frame larger than 1 MiB. Send smaller frames and reconnect."
                )
            else:
                LOG.info(
                    "StackChan connection closed during a session. Reconnect the device and "
                    "retry the turn."
                )
        except ConnectionClosedOK:
            LOG.info("StackChan session closed. Reconnect the device to start another turn.")
        except Exception as exc:
            LOG.info("StackChan session ended: %s", type(exc).__name__)
        finally:
            if self.turn_handler is not None:
                try:
                    await self.turn_handler(session_id, device_id, "abort")
                except Exception:
                    LOG.warning("Could not cancel the StackChan voice turn on disconnect")
            if device_id in self._camera_streaming:
                await self._stop_camera(device_id)
            camera_disconnected = getattr(self.robot, "camera_disconnected", None)
            if callable(camera_disconnected):
                try:
                    await asyncio.to_thread(camera_disconnected)
                except Exception:
                    LOG.warning("Could not clear StackChan camera indicator on disconnect")
            if self._sessions.get(device_id) is websocket:
                self._sessions.pop(device_id, None)
                self._session_credentials.pop(device_id, None)
                self._session_features.pop(device_id, None)
                self._session_ids.pop(device_id, None)
                self._early_device_replies.clear()
            if not self._sessions:
                self._session_ready.clear()
            self._speaking.discard(device_id)
            for request_id, (future, _name, pending_device_id) in list(
                self._pending_device_calls.items()
            ):
                if pending_device_id != device_id:
                    continue
                if not future.done():
                    future.set_exception(
                        ConnectionError(
                            "StackChan disconnected during a command. Reconnect and retry."
                        )
                    )
                self._pending_device_calls.pop(request_id, None)

    async def _mcp(self, ws: ServerConnection, session_id: str, payload: dict[str, Any]) -> None:
        request_id = payload.get("id")
        if "result" in payload or "error" in payload:
            if type(request_id) is not int:
                LOG.warning("StackChan sent an MCP reply without a numeric id; ignoring it.")
                return
            request_key = str(request_id)
            call = self._pending_device_calls.pop(request_key, None)
            pending = call[0] if call is not None else None
            if pending is None:
                self._prune_early_device_replies()
                deadline = self._device_call_deadlines.get(request_key)
                if deadline is None or deadline <= time.monotonic():
                    return
                self._early_device_replies[request_key] = payload
                while len(self._early_device_replies) > MAX_EARLY_DEVICE_REPLIES:
                    self._early_device_replies.pop(next(iter(self._early_device_replies)))
                return
            if pending is not None:
                self._resolve_device_reply(pending, payload)
            return
        if payload.get("method") == "ping" and "id" in payload:
            await self._json(
                ws,
                session_id,
                "mcp",
                {"payload": {"jsonrpc": "2.0", "id": request_id, "result": {}}},
            )

        elif payload.get("method") == "initialize" and "id" in payload:
            device_id = next((key for key, active in self._sessions.items() if active is ws), None)
            if device_id is None:
                return
            token = self._session_credentials[device_id][1]
            url = self._vision_url(device_id)
            await self._json(
                ws,
                session_id,
                "mcp",
                {
                    "payload": {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {
                                "tools": {"listChanged": False},
                                "vision": {"url": url, "token": token},
                            },
                            "serverInfo": {"name": self.server_name, "version": self.version},
                        },
                    }
                },
            )

    def _vision_url(self, device_id: str) -> str:
        if self.advertised_vision_url:
            base = self.advertised_vision_url.rstrip("/")
            return base if "/vision/" in base else f"{base}/vision/{device_id}"
        host = self.vision_host
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        return f"http://{host}:{self.vision_port}/vision/{device_id}"

    async def _receive_photo(self, request: web.Request) -> web.Response:
        device_id = request.match_info["device_id"]
        credentials = self._session_credentials.get(device_id)
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else request.query.get("token")
        if credentials is None or not self.pairing.authorize(device_id, *credentials):
            raise web.HTTPUnauthorized()
        if token is None or not self.pairing.authorize(device_id, credentials[0], token):
            raise web.HTTPForbidden()
        if request.content_length is not None and request.content_length > self.max_photo_bytes:
            raise web.HTTPRequestEntityTooLarge(
                max_size=self.max_photo_bytes, actual_size=request.content_length
            )
        if not request.content_type.startswith("multipart/"):
            raise web.HTTPUnsupportedMediaType(text="Expected multipart JPEG upload")
        reader = await request.multipart()
        photo: bytes | None = None
        total = 0
        async for field in reader:
            if field.name not in {"image", "file", "photo"}:
                await field.release()
                continue
            chunks: list[bytes] = []
            while chunk := await field.read_chunk(64 * 1024):
                total += len(chunk)
                if total > self.max_photo_bytes:
                    raise web.HTTPRequestEntityTooLarge(
                        max_size=self.max_photo_bytes, actual_size=total
                    )
                chunks.append(chunk)
            photo = b"".join(chunks)
        if photo is None or not photo.startswith(b"\xff\xd8"):
            raise web.HTTPBadRequest(text="Multipart request must include a JPEG image field")
        self._photos[device_id] = photo
        waiter = self._photo_waiters.get(device_id)
        if waiter is not None and not waiter.done():
            waiter.set_result(photo)
        return web.json_response({"accepted": True, "size": len(photo)})

    async def take_photo(self, device_id: str | None = None) -> bytes | None:
        if device_id is None:
            if len(self._sessions) != 1:
                raise ConnectionError("Select one authenticated StackChan before taking a photo")
            device_id = next(iter(self._sessions))
        self._photos.pop(device_id, None)
        future = asyncio.get_running_loop().create_future()
        self._photo_waiters[device_id] = future
        try:
            await asyncio.to_thread(
                self.call_device_tool,
                "self.camera.take_photo",
                {"question": "Describe what you see."},
            )
            return await asyncio.wait_for(future, timeout=10)
        finally:
            self._photo_waiters.pop(device_id, None)
            if not future.done():
                future.cancel()

    async def stream_camera(self, enabled: bool = True) -> object:
        if len(self._sessions) != 1:
            raise ConnectionError("Select one authenticated StackChan before streaming its camera")
        device_id = next(iter(self._sessions))
        if enabled:
            if getattr(getattr(self.robot, "robot", None), "estop_engaged", False):
                raise EstopEngaged("camera stream refused while the emergency stop is engaged")
            self._camera_streaming.add(device_id)
            return True
        self._camera_streaming.discard(device_id)
        return True

    async def send_avatar_frame(self, frame: bytes) -> None:
        decoded = decode_frame(frame)
        if decoded.command != AvatarCommand.START_CAMERA_STREAM:
            raise ValueError("unsupported avatar frame command")
        enabled = decoded.payload != b"\x00"
        await self.stream_camera(enabled)

    async def send_expression_frame(self, frame: bytes) -> None:
        if self._avatar_frame_sender is None:
            raise ConnectionError(
                "StackChan avatar channel is unavailable. Connect the avatar service and retry."
            )
        if len(self._sessions) != 1:
            raise ConnectionError(
                "Select one authenticated StackChan before sending an expression."
            )
        await self._avatar_frame_sender(next(iter(self._sessions)), frame)

    async def _stop_camera(self, device_id: str) -> None:
        self._camera_streaming.discard(device_id)
        camera_disconnected = getattr(self.robot, "camera_disconnected", None)
        if callable(camera_disconnected):
            try:
                result = camera_disconnected()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                LOG.warning("Could not clear StackChan camera indicator")

    def _prune_early_device_replies(self) -> None:
        now = time.monotonic()
        for request_key in list(self._early_device_replies):
            deadline = self._device_call_deadlines.get(request_key)
            if deadline is None or deadline <= now:
                self._early_device_replies.pop(request_key, None)

    def _allow_pairing_request(self, source: str) -> bool:
        now = time.monotonic()
        recent = [stamp for stamp in self._source_requests.get(source, []) if now - stamp < 600]
        self._source_requests[source] = recent
        if len(recent) >= 8:
            self._source_requests[source] = recent
            return False
        recent.append(now)
        self._source_requests[source] = recent
        return True

    @staticmethod
    async def _close_stale_session(stale: ServerConnection) -> None:
        try:
            await asyncio.wait_for(
                stale.close(
                    code=1012,
                    reason="Superseded by a reconnect from this Device-Id.",
                ),
                timeout=0.1,
            )
        except TimeoutError:
            transport = getattr(stale, "transport", None)
            if transport is not None:
                transport.abort()
        except Exception as exc:
            LOG.debug("Could not close superseded StackChan session: %s", type(exc).__name__)

    async def _json(
        self,
        ws: ServerConnection,
        session_id: str,
        kind: str,
        payload: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> None:
        obj = {"session_id": session_id, "type": kind, **payload}
        if extra:
            obj.update(extra)
        await ws.send(json.dumps(obj))

    async def _send_error(
        self, ws: ServerConnection, session_id: str, code: int, message: str
    ) -> None:
        await self._json(ws, session_id, "error", {"code": code, "message": message})

    async def send_audio(
        self,
        device_id: str,
        frames: list[bytes],
        *,
        sentence_start: bool = False,
        start: bool = True,
        stop: bool = True,
        prebuffer: int = 3,
    ) -> None:
        """Send encoded 24 kHz Opus frames; the first `prebuffer` go fast, the rest paced."""
        websocket = self._sessions.get(device_id)
        if self._sessions.get(device_id) is not websocket or not self._session_authorized(
            device_id
        ):
            raise PermissionError(
                "No authenticated active session exists for this Device-Id. Pair it and "
                "reconnect before sending audio."
            )
        if start:
            self._speaking.add(device_id)
            await self._json(websocket, self._session_ids[device_id], "tts", {"state": "start"})
            # The firmware drops audio until it has switched from listening to speaking;
            # frames sent right behind tts start were lost (stutter heard on 2026-10-19).
            await asyncio.sleep(SPEAK_SETTLE_S)
        if sentence_start:
            await self._json(
                websocket, self._session_ids[device_id], "tts", {"state": "sentence_start"}
            )
        interval = 0.06
        deadline = time.monotonic()
        try:
            for index, frame in enumerate(frames):
                if device_id not in self._speaking:
                    break
                if index >= prebuffer:
                    deadline = (
                        time.monotonic() + interval if index == prebuffer else deadline + interval
                    )
                    await asyncio.sleep(max(0.0, deadline - time.monotonic()))
                    if device_id not in self._speaking:
                        break
                elif index > 0:
                    await asyncio.sleep(PREBUFFER_GAP_S)
                await websocket.send(frame)
        finally:
            if stop:
                self._speaking.discard(device_id)
                await self._json(websocket, self._session_ids[device_id], "tts", {"state": "stop"})

    async def stop_audio(self, device_id: str) -> None:
        """Stop a current reply promptly; the sender observes this before its next frame."""
        self._speaking.discard(device_id)
        websocket = self._sessions.get(device_id)
        if websocket is not None and self._session_authorized(device_id):
            await self._json(websocket, self._session_ids[device_id], "tts", {"state": "stop"})

    def call_device_tool(
        self, name: str, arguments: dict[str, object], *, timeout: float = 5.0
    ) -> object:
        if not self._sessions:
            raise ConnectionError(
                "No StackChan is connected. Connect and pair the robot, then retry."
            )
        if len(self._sessions) != 1:
            raise ConnectionError(
                "More than one StackChan is connected. Select a device before sending a command."
            )
        device_id, websocket = next(iter(self._sessions.items()))
        if not self._session_authorized(device_id):
            raise PermissionError("StackChan pairing is revoked. Approve and provision it again.")
        if name == "self.camera.take_photo":
            if self.robot is None:
                raise NotSupported(
                    "StackChan camera has no Robot indicator adapter; configure the body Robot "
                    "first."
                )
            return asyncio.run_coroutine_threadsafe(
                self.robot.take_photo(device_id), self._loop
            ).result(timeout=timeout + 1)
        # StackChan firmware parses MCP request ids as numeric JSON-RPC ids.
        request_id = next(self._next_device_request_id)
        request_key = str(request_id)
        if self._loop is None:
            raise ConnectionError(
                "StackChan service is not running. Start the Bot body service and retry."
            )
        deadline = time.monotonic() + timeout
        try:
            asyncio.run_coroutine_threadsafe(
                self._register_device_reply(request_key, device_id, name, deadline), self._loop
            ).result(timeout=max(0, deadline - time.monotonic()))
            asyncio.run_coroutine_threadsafe(
                self._send_device_tool(device_id, websocket, request_id, name, arguments),
                self._loop,
            ).result(timeout=max(0, deadline - time.monotonic()))
            return asyncio.run_coroutine_threadsafe(
                self._await_device_reply(request_key, device_id, name, timeout), self._loop
            ).result(timeout=max(0, deadline - time.monotonic()))
        except concurrent.futures.CancelledError as exc:
            raise EstopEngaged(
                "head move was cancelled by the software stop; release it before moving again"
            ) from exc
        except concurrent.futures.TimeoutError as exc:
            raise TimeoutError(
                f"StackChan did not answer {name} within {timeout:g} seconds. "
                "Check its connection and retry."
            ) from exc
        finally:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._discard_pending(request_key), self._loop
                ).result(timeout=1)
            except (concurrent.futures.TimeoutError, RuntimeError):
                pass

    def device_supports(self, feature: str) -> bool:
        if len(self._sessions) != 1:
            return False
        device_id = next(iter(self._sessions))
        return self._session_features.get(device_id, {}).get(feature) is True

    def create_notification_audio(self, message: object) -> str:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("notification message must be non-empty text")
        if self.notification_audio_handler is None:
            raise NotSupported(
                "Host notification audio is not configured",
                part="audio",
                capability="speaker",
                fix="Configure the host TTS audio provider, then retry.",
            )
        if len(self._sessions) != 1:
            raise ConnectionError("A single paired StackChan session is required")
        device_id = next(iter(self._sessions))
        token = uuid.uuid4().hex
        audio = asyncio.run_coroutine_threadsafe(
            self.notification_audio_handler(message), self._loop
        ).result(timeout=10)
        if not isinstance(audio, bytes) or not audio:
            raise BodyLost("Host notification audio provider returned no audio")
        self._notification_audio[(device_id, token)] = audio
        return self._notify_audio_url(device_id, token)

    def _notify_audio_url(self, device_id: str, audio_id: str) -> str:
        base = self.advertised_vision_url
        if base:
            root = base.split("/vision/", 1)[0].rstrip("/")
        else:
            host = self.vision_host if self.vision_host not in {"0.0.0.0", "::"} else "127.0.0.1"
            root = f"http://{host}:{self.vision_port}"
        return f"{root}/notify/{device_id}/{audio_id}.ogg"

    async def send_notify(self, audio_url: str) -> None:
        if not self.device_supports("notify"):
            raise NotSupported("StackChan did not advertise notify in hello features")
        if len(self._sessions) != 1:
            raise ConnectionError("A single paired StackChan session is required")
        device_id, websocket = next(iter(self._sessions.items()))
        session_id = self._session_ids[device_id]
        # xiaozhi-esp32 v2.3.0 main/protocols/websocket_protocol.cc at
        # 1b48ebd7863695bf80d384c6c09af6299a6d7d0e documents hello features;
        # its source has no notify handler, so the notify frame is gated by hello.
        await self._json(websocket, session_id, "notify", {"audio_url": audio_url})

    async def send_emotion(self, expression: str) -> str:
        """Set the face over the voice channel, which works in AI Agent mode.

        xiaozhi-esp32 application.cc hands an `llm` frame's emotion to the
        display; the StackChan display maps it onto the avatar.
        """
        emotion = FIRMWARE_EMOTIONS.get(expression)
        if emotion is None:
            raise ValueError(f"Pick one of: {', '.join(FIRMWARE_EMOTIONS)}.")
        if len(self._sessions) != 1:
            raise ConnectionError("A single paired StackChan session is required")
        device_id, websocket = next(iter(self._sessions.items()))
        await self._json(websocket, self._session_ids[device_id], "llm", {"emotion": emotion})
        return emotion

    async def _serve_notify_audio(self, request: web.Request) -> web.Response:
        device_id = request.match_info["device_id"]
        audio_id = request.match_info["audio_id"]
        credentials = self._session_credentials.get(device_id)
        auth = request.headers.get("Authorization", "")
        if credentials is None or not self.pairing.authorize(device_id, *credentials):
            raise web.HTTPUnauthorized()
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not self.pairing.authorize(device_id, credentials[0], token):
            raise web.HTTPForbidden()
        audio = self._notification_audio.pop((device_id, audio_id), None)
        if audio is None:
            raise web.HTTPNotFound()
        return web.Response(
            body=audio, content_type="audio/ogg", headers={"Cache-Control": "no-store"}
        )

    def cancel_device_calls(self, name: str) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._cancel_device_calls, name)

    async def _await_device_reply(
        self, request_key: str, device_id: str, name: str, timeout: float
    ) -> object:
        future = self._pending_device_calls[request_key][0]
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending_device_calls.pop(request_key, None)
            self._device_call_deadlines.pop(request_key, None)
            self._early_device_replies.pop(request_key, None)

    async def _discard_pending(self, request_key: str) -> None:
        self._pending_device_calls.pop(request_key, None)
        self._device_call_deadlines.pop(request_key, None)
        self._early_device_replies.pop(request_key, None)

    async def _register_device_reply(
        self, request_key: str, device_id: str, name: str, deadline: float
    ) -> None:
        self._device_call_deadlines[request_key] = deadline
        future = asyncio.get_running_loop().create_future()
        self._pending_device_calls[request_key] = (future, name, device_id)
        early = self._early_device_replies.pop(request_key, None)
        deadline = self._device_call_deadlines.get(request_key)
        if early is not None and deadline is not None and deadline > time.monotonic():
            self._resolve_device_reply(future, early)

    @staticmethod
    def _resolve_device_reply(future: asyncio.Future[object], payload: dict[str, Any]) -> None:
        if future.done():
            return
        if "error" in payload:
            error = payload.get("error") or {}
            future.set_exception(
                RuntimeError(str(error.get("message", "device returned an error")))
            )
            return
        try:
            future.set_result(XiaozhiServer._device_result(payload.get("result")))
        except RuntimeError as exc:
            future.set_exception(exc)

    @staticmethod
    def _device_result(result: object) -> object:
        if isinstance(result, dict) and result.get("isError"):
            content = result.get("content", [])
            details = [
                item.get("text")
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            message = "; ".join(details) or "StackChan reported a tool error."
            raise RuntimeError(message)
        content = result.get("content", []) if isinstance(result, dict) else []
        if content and isinstance(content[0], dict):
            try:
                return json.loads(content[0].get("text", "true"))
            except (TypeError, json.JSONDecodeError):
                return content[0].get("text")
        return True

    def _cancel_device_calls(self, name: str) -> None:
        for future, pending_name, _device_id in self._pending_device_calls.values():
            if pending_name == name and not future.done():
                future.cancel()

    async def _send_device_tool(
        self,
        device_id: str,
        websocket: ServerConnection,
        request_id: int,
        name: str,
        arguments: dict[str, object],
    ) -> None:
        if websocket not in self._sessions.values():
            raise ConnectionError(
                "StackChan disconnected before the command was sent. Reconnect and retry."
            )
        if not self._session_authorized(device_id):
            raise PermissionError(
                "StackChan pairing is no longer approved. Reapprove and reconnect."
            )
        await websocket.send(
            json.dumps(
                {
                    "type": "mcp",
                    "payload": {
                        "jsonrpc": "2.0",
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                        "id": request_id,
                    },
                }
            )
        )

    def _session_authorized(self, device_id: str) -> bool:
        credentials = self._session_credentials.get(device_id)
        if credentials is None:
            return False
        client_id, token = credentials
        return self.pairing.authorize(device_id, client_id, token)
