"""Small xiaozhi WebSocket endpoint for the StackChan voice and tool channel."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from .pairing import PairingStore

LOG = logging.getLogger(__name__)


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
        robot: RobotAdapter,
        audio_handler: AudioHandler | None = None,
        *,
        version: str = "1",
        server_name: str = "MaiPai Bot",
        idle_timeout: float = 30.0,
    ) -> None:
        self.pairing = pairing
        self.robot = robot
        self.audio_handler = audio_handler
        self.version = version
        self.server_name = server_name
        self.idle_timeout = idle_timeout
        self._server: Any = None
        self._sessions: dict[str, ServerConnection] = {}
        self._speaking: set[str] = set()
        self._session_ready = asyncio.Event()

    async def start(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        self._server = await serve(
            self.handle, host, port, max_size=2**20, ping_interval=20, ping_timeout=20
        )

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def handle(self, websocket: ServerConnection) -> None:
        device_id = websocket.request.headers.get("Device-Id", "")
        client_id = websocket.request.headers.get("Client-Id", "")
        protocol_version = websocket.request.headers.get("Protocol-Version", "1")
        auth = websocket.request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else None
        if not self.pairing.authorize(device_id, client_id, token):
            try:
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
                    "Device is not approved. Ask a MaiPai admin to approve this Device-Id "
                    "in the pairing screen, then provision its token."
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
        if self._sessions.get(device_id) is not None:
            await websocket.close(
                code=1008,
                reason=(
                    "This Device-Id already has an active session. Close the other "
                    "connection, then reconnect."
                ),
            )
            return
        self._sessions[device_id] = websocket
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
                if isinstance(message, bytes):
                    if self.audio_handler:
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
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "hello",
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
                    if data.get("state") in {"start", "detect"}:
                        if data.get("mode") == "realtime":
                            await self._json(websocket, session_id, "tts", {"state": "start"})
                    elif data.get("state") == "stop":
                        await self._json(websocket, session_id, "tts", {"state": "stop"})
                elif kind == "abort":
                    self._speaking.discard(device_id)
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
            if self._sessions.get(device_id) is websocket:
                self._sessions.pop(device_id, None)
            if not self._sessions:
                self._session_ready.clear()
            self._speaking.discard(device_id)

    async def _mcp(self, ws: ServerConnection, session_id: str, payload: dict[str, Any]) -> None:
        method = payload.get("method")
        request_id = payload.get("id")
        try:
            if method == "initialize":
                result: object = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": self.server_name, "version": self.version},
                }
            elif method == "tools/list":
                result = {"tools": self._tools(), "nextCursor": ""}
            elif method == "tools/call":
                params = payload.get("params", {})
                result = await self._call_tool(
                    params.get("name", ""), params.get("arguments") or {}
                )
            elif "result" in payload or "error" in payload:
                return
            elif method == "ping":
                result = {}
            else:
                await self._mcp_error(
                    ws,
                    session_id,
                    request_id,
                    -32601,
                    "Unknown MCP method. Use initialize, tools/list, or tools/call.",
                )
                return
            await self._json(
                ws,
                session_id,
                "mcp",
                {"payload": {"jsonrpc": "2.0", "id": request_id, "result": result}},
            )
        except (ValueError, TypeError, KeyError) as exc:
            await self._mcp_error(ws, session_id, request_id, -32602, str(exc))
        except Exception:
            LOG.exception("StackChan tool call failed")
            await self._mcp_error(
                ws,
                session_id,
                request_id,
                -32603,
                "The robot command failed. Check the body connection and retry.",
            )

    @staticmethod
    def _tools() -> list[dict[str, Any]]:
        return [
            {
                "name": "self.robot.get_head_angles",
                "description": "Read current head angles.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "self.robot.set_head_angles",
                "description": "Move head; yaw -128..128, pitch 5..85, speed 100..1000.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "yaw": {"type": "integer", "minimum": -128, "maximum": 128},
                        "pitch": {"type": "integer", "minimum": 5, "maximum": 85},
                        "speed": {"type": "integer", "minimum": 100, "maximum": 1000},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "self.robot.set_led_color",
                "description": "Set the robot's internal LEDs, 0..168 per channel.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "red": {"type": "integer", "minimum": 0, "maximum": 168},
                        "green": {"type": "integer", "minimum": 0, "maximum": 168},
                        "blue": {"type": "integer", "minimum": 0, "maximum": 168},
                    },
                    "required": ["red", "green", "blue"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "self.audio_speaker.set_volume",
                "description": "Set speaker volume, 0..100.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"volume": {"type": "integer", "minimum": 0, "maximum": 100}},
                    "required": ["volume"],
                    "additionalProperties": False,
                },
            },
        ]

    async def _call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "self.robot.get_head_angles":
            getter = getattr(self.robot, "get_head_angles", None)
            if getter is None:
                raise ValueError(
                    "Robot adapter cannot read head angles. Connect a supported profile "
                    "adapter and retry."
                )
            value = getter()
            if asyncio.iscoroutine(value):
                value = await value
        if name == "self.robot.set_head_angles":
            yaw = args.get("yaw")
            pitch = args.get("pitch")
            speed = args.get("speed", 150)
            if yaw is not None and (type(yaw) is not int or not -128 <= yaw <= 128):
                raise ValueError(
                    "Yaw must be an integer from -128 to 128. Correct the value and retry."
                )
            if pitch is not None and (type(pitch) is not int or not 5 <= pitch <= 85):
                raise ValueError(
                    "Pitch must be an integer from 5 to 85. Correct the value and retry."
                )
            if type(speed) is not int or not 100 <= speed <= 1000:
                raise ValueError(
                    "Speed must be an integer from 100 to 1000. Correct the value and retry."
                )
            value = await self.robot.set_head_angles(yaw, pitch, speed)
        elif name == "self.robot.set_led_color":
            rgb = [args.get(k) for k in ("red", "green", "blue")]
            if any(type(v) is not int or not 0 <= v <= 168 for v in rgb):
                raise ValueError(
                    "LED channels must be integers from 0 to 168. Correct the colors and retry."
                )
            value = await self.robot.set_led_color(*rgb)
        elif name == "self.audio_speaker.set_volume":
            volume = args.get("volume")
            if type(volume) is not int or not 0 <= volume <= 100:
                raise ValueError(
                    "Volume must be an integer from 0 to 100. Correct the value and retry."
                )
            value = await self.robot.set_volume(volume)
        else:
            raise ValueError(
                f"Unknown StackChan tool {name!r}. Call tools/list to see supported tools."
            )
        return {
            "content": [{"type": "text", "text": json.dumps(value if value is not None else True)}],
            "isError": False,
        }

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

    async def _mcp_error(
        self, ws: ServerConnection, session_id: str, request_id: object, code: int, message: str
    ) -> None:
        await self._json(
            ws,
            session_id,
            "mcp",
            {
                "payload": {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": code, "message": message},
                }
            },
        )

    async def send_audio(self, device_id: str, frames: list[bytes]) -> None:
        """Send already encoded 24 kHz Opus frames; codec and pacing belong upstream."""
        websocket = self._sessions.get(device_id)
        if (
            self._sessions.get(device_id) is not websocket
            or device_id not in self.pairing.allowed_device_ids()
        ):
            raise PermissionError(
                "No authenticated active session exists for this Device-Id. Pair it and "
                "reconnect before sending audio."
            )
        self._speaking.add(device_id)
        await websocket.send(json.dumps({"type": "tts", "state": "start"}))
        try:
            for frame in frames:
                if device_id not in self._speaking:
                    break
                await websocket.send(frame)
                await asyncio.sleep(0.06)
        finally:
            self._speaking.discard(device_id)
            await websocket.send(json.dumps({"type": "tts", "state": "stop"}))
