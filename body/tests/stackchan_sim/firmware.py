"""Small asynchronous StackChan firmware simulator for end-to-end tests."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

DEVICE_ID = "02:00:00:00:00:51"
CLIENT_ID = "00000000-0000-4000-8000-000000000051"
OPUS_FRAME = b"\xf8\xff\xfe" + bytes(range(117))
MAX_SPEED = 150


class StackChanFirmware:
    """Model the pinned StackChan websocket headers, MCP tools, and turn frames."""

    def __init__(
        self,
        url: str,
        token: str | None,
        *,
        device_id: str = DEVICE_ID,
        client_id: str = CLIENT_ID,
        persistent_channel: bool = True,
        idle_timeout: float = 0.1,
        backoff: tuple[float, float] = (0.01, 0.05),
    ) -> None:
        self.url = url
        self.token = token
        self.device_id = device_id
        self.client_id = client_id
        self.persistent_channel = persistent_channel
        self.idle_timeout = idle_timeout
        self.backoff = backoff
        self.websocket: ClientConnection | None = None
        self.server_hello: dict[str, Any] | None = None
        self.head_angles = {"yaw": 0.0, "pitch": 45.0}
        self._motion_start = dict(self.head_angles)
        self._motion_target = dict(self.head_angles)
        self._motion_started_at = time.monotonic()
        self._motion_duration = 0.0
        self.led_color = (0, 0, 0)
        self.led_colors = ((0, 0, 0),) * 12
        self.camera_indicator_active = False
        self.volume = 50
        self.tool_calls: list[tuple[str, dict[str, Any]]] = []
        self.motion_commands: list[tuple[dict[str, int], dict[str, int]]] = []
        self.angle_reads: list[dict[str, int]] = []
        self.audio_uplink: list[bytes] = []
        self.audio_downlink: list[bytes] = []
        self.tts_frames: list[dict[str, Any]] = []
        self.mcp_responses: dict[int, dict[str, Any]] = {}
        self.device_mcp_responses: dict[int, dict[str, Any]] = {}
        self.close_reasons: list[tuple[int, str]] = []
        self.connection_count = 0
        self._request_id = 0
        self._runner: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.connected = asyncio.Event()
        self.disconnected = asyncio.Event()
        self.disconnected.set()

    @property
    def current_angles(self) -> dict[str, int]:
        now = time.monotonic()
        if self._motion_duration <= 0:
            fraction = 1.0
        else:
            fraction = min(1.0, max(0.0, (now - self._motion_started_at) / self._motion_duration))
        self.head_angles = {
            axis: self._motion_start[axis]
            + (self._motion_target[axis] - self._motion_start[axis]) * fraction
            for axis in ("yaw", "pitch")
        }
        return {axis: round(value) for axis, value in self.head_angles.items()}

    def set_token(self, token: str) -> None:
        self.token = token

    async def start(self) -> None:
        if self._runner is not None:
            return
        self._stop.clear()
        self._runner = asyncio.create_task(self._reconnect_loop())

    async def stop(self) -> None:
        self._stop.set()
        websocket = self.websocket
        if websocket is not None:
            await websocket.close()
        if self._runner is not None:
            await self._runner
            self._runner = None

    async def wait_connected(self, timeout: float = 2.0) -> None:
        await asyncio.wait_for(self.connected.wait(), timeout)

    async def wait_tool_call(self, name: str, *, after: int = 0, timeout: float = 2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            matches = [call for call in self.tool_calls[after:] if call[0] == name]
            if matches:
                return matches[-1]
            await asyncio.sleep(0.005)
        raise TimeoutError(f"firmware did not receive {name} before the test deadline")

    async def wait_connections(self, count: int, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while self.connection_count < count and time.monotonic() < deadline:
            await asyncio.sleep(0.005)
        if self.connection_count < count:
            raise TimeoutError(
                f"firmware made {self.connection_count} connections, expected {count}"
            )

    async def wait_mcp_response(self, request_id: int, timeout: float = 1.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if request_id in self.mcp_responses:
                return self.mcp_responses[request_id]
            await asyncio.sleep(0.005)
        raise TimeoutError(f"firmware did not receive MCP response {request_id}")

    def hold_close_response(self) -> None:
        """Leave the peer half-open by pausing reads before the service sends close."""
        if self.websocket is None:
            raise ConnectionError("StackChan firmware has no active websocket")
        self.websocket.transport.pause_reading()

    def resume_close_response(self) -> None:
        if self.websocket is not None:
            self.websocket.transport.resume_reading()

    async def ping(self) -> int:
        self._request_id += 1
        request_id = self._request_id
        await self._send_json(
            {
                "type": "mcp",
                "payload": {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "ping",
                    "params": {},
                },
            }
        )
        return request_id

    async def send_audio_uplink(self) -> None:
        await self._send_json({"type": "listen", "state": "start", "mode": "manual"})
        await self._send_binary(OPUS_FRAME)
        await self._send_json({"type": "listen", "state": "stop"})
        if not self.persistent_channel:
            await self.websocket.close()  # type: ignore[union-attr]

    async def send_mcp_request(
        self, method: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send an MCP request for protocol tests and return the firmware reply."""
        self._request_id += 1
        request_id = self._request_id
        waiter: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._mcp_waiters[request_id] = waiter
        await self._send_json(
            {
                "type": "mcp",
                "payload": {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": dict(params or {}),
                },
            }
        )
        return await asyncio.wait_for(waiter, timeout=1.0)

    _mcp_waiters: dict[int, asyncio.Future[dict[str, Any]]]

    async def _reconnect_loop(self) -> None:
        delay = self.backoff[0]
        while not self._stop.is_set():
            headers = {
                "Device-Id": self.device_id,
                "Client-Id": self.client_id,
                "Protocol-Version": "1",
            }
            if self.token is not None:
                headers["Authorization"] = f"Bearer {self.token}"
            try:
                async with connect(self.url, additional_headers=headers, ping_interval=None) as ws:
                    self.websocket = ws
                    self._mcp_waiters = {}
                    self.connection_count += 1
                    self.disconnected.clear()
                    await self._send_json(
                        {
                            "type": "hello",
                            "version": 1,
                            "features": {"mcp": True},
                            "transport": "websocket",
                            "audio_params": {
                                "format": "opus",
                                "sample_rate": 16000,
                                "channels": 1,
                                "frame_duration": 60,
                            },
                        }
                    )
                    hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.0))
                    if hello.get("type") != "hello":
                        raise RuntimeError("service did not answer firmware hello")
                    self.server_hello = hello
                    self.connected.set()
                    delay = self.backoff[0]
                    await self._receive_loop(ws)
            except ConnectionClosed as exc:
                close = exc.rcvd or exc.sent
                if close is not None:
                    self.close_reasons.append((close.code, close.reason))
            except (InvalidStatus, OSError, TimeoutError, RuntimeError):
                pass
            finally:
                self.websocket = None
                self.connected.clear()
                self.disconnected.set()
            if self._stop.is_set():
                return
            await asyncio.sleep(delay)
            delay = min(self.backoff[1], delay * 2)

    async def _receive_loop(self, ws: ClientConnection) -> None:
        while not self._stop.is_set():
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=self.idle_timeout)
            except TimeoutError:
                if self.persistent_channel:
                    continue
                await ws.close()
                return
            except ConnectionClosed as exc:
                close = exc.rcvd or exc.sent
                if close is not None:
                    self.close_reasons.append((close.code, close.reason))
                return
            if isinstance(message, bytes):
                self.audio_downlink.append(message)
                continue
            data = json.loads(message)
            kind = data.get("type")
            if kind == "mcp":
                payload = data.get("payload", {})
                request_id = payload.get("id")
                waiter = self._mcp_waiters.get(request_id)
                if waiter is not None and not waiter.done():
                    waiter.set_result(payload)
                elif isinstance(request_id, int) and ("result" in payload or "error" in payload):
                    self.mcp_responses[request_id] = payload
                elif payload.get("method") == "tools/call":
                    await self._serve_tool_call(ws, payload)
                elif payload.get("method") == "initialize" or payload.get("method") == "tools/list":
                    await self._serve_mcp_method(ws, payload)
            elif kind == "tts":
                self.tts_frames.append(data)

    async def _serve_tool_call(self, ws: ClientConnection, request: dict[str, Any]) -> None:
        params = request.get("params", {})
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        self.tool_calls.append((name, dict(arguments)))
        result = self._run_tool(name, arguments)
        await self._send_json(
            {
                "type": "mcp",
                "payload": {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
                },
            },
            ws=ws,
        )

    async def _serve_mcp_method(self, ws: ClientConnection, request: dict[str, Any]) -> None:
        method = request.get("method")
        if method == "initialize":
            result: dict[str, Any] = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "StackChan", "version": "pinned-firmware"},
            }
        else:
            result = {
                "tools": [
                    {"name": name, "inputSchema": {"type": "object"}}
                    for name in (
                        "self.robot.get_head_angles",
                        "self.robot.set_head_angles",
                        "self.robot.set_led_color",
                        "self.robot.set_led_colors",
                        "self.audio_speaker.set_volume",
                    )
                ]
            }
        response = {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": result,
        }
        if isinstance(request.get("id"), int):
            self.device_mcp_responses[request["id"]] = response
        await self._send_json(
            {
                "type": "mcp",
                "payload": response,
            },
            ws=ws,
        )

    def _run_tool(self, name: str, arguments: Mapping[str, Any]) -> object:
        if name == "self.robot.get_head_angles":
            angles = self.current_angles
            self.angle_reads.append(dict(angles))
            return angles
        if name == "self.robot.set_head_angles":
            current = self.current_angles
            previous_target = dict(self._motion_target)
            target = {
                "yaw": (
                    previous_target["yaw"]
                    if arguments.get("yaw") == -9999
                    else float(arguments["yaw"])
                ),
                "pitch": (
                    previous_target["pitch"]
                    if arguments.get("pitch") == -9999
                    else float(arguments["pitch"])
                ),
            }
            self.motion_commands.append((dict(target), dict(current)))
            speed = max(1, min(MAX_SPEED, int(arguments.get("speed", MAX_SPEED))))
            duration = max(abs(target[axis] - current[axis]) for axis in target) / speed
            self._motion_start = {axis: float(current[axis]) for axis in current}
            self._motion_target = target
            self._motion_started_at = time.monotonic()
            self._motion_duration = duration
            return {"accepted": True, **target}
        if name == "self.robot.set_led_color":
            self.led_color = tuple(int(arguments[key]) for key in ("red", "green", "blue"))
            self.led_colors = (self.led_color,) * 12
            return {"accepted": True}
        if name == "self.robot.set_led_colors":
            colors = [
                tuple(
                    int(arguments[f"led_{index}_{channel}"]) for channel in ("red", "green", "blue")
                )
                for index in range(12)
            ]
            if self.camera_indicator_active:
                self.led_color = (168, 0, 0)
                self.led_colors = (self.led_color,) * 12
            else:
                self.led_colors = tuple(colors)
                self.led_color = colors[0] if len(set(colors)) == 1 else (-1, -1, -1)
            return {"accepted": True}
        if name == "self.audio_speaker.set_volume":
            self.volume = int(arguments["volume"])
            return {"accepted": True}
        return {"isError": True, "content": [{"type": "text", "text": f"unsupported tool: {name}"}]}

    async def _send_json(self, data: dict[str, Any], *, ws: ClientConnection | None = None) -> None:
        target = ws or self.websocket
        if target is None:
            raise ConnectionError("StackChan firmware has no active websocket")
        await target.send(json.dumps(data))

    async def _send_binary(self, data: bytes) -> None:
        if self.websocket is None:
            raise ConnectionError("StackChan firmware has no active websocket")
        self.audio_uplink.append(data)
        await self.websocket.send(data)
