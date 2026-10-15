"""Small xiaozhi WebSocket endpoint for the StackChan voice and tool channel."""

from __future__ import annotations

import asyncio
import concurrent.futures
import itertools
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from maipai_body.hal.errors import BodyLost, EstopEngaged

from .pairing import PairingStore

LOG = logging.getLogger(__name__)
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
            raise ValueError(
                "StackChan returned invalid head angles. Check firmware compatibility."
            )
        return result

    def set_head_angles(self, yaw: int | None, pitch: int | None, speed: int) -> object:
        try:
            return self._call(
                "self.robot.set_head_angles",
                {
                    "yaw": yaw if yaw is not None else -9999,
                    "pitch": pitch if pitch is not None else -9999,
                    "speed": speed,
                },
            )
        except concurrent.futures.CancelledError as exc:
            raise EstopEngaged(
                "head move was cancelled by the software stop; release it before moving again"
            ) from exc
        except (ConnectionError, TimeoutError) as exc:
            raise BodyLost(
                "StackChan did not confirm the head command. Reconnect it before moving again."
            ) from exc

    def set_led_color(self, red: int, green: int, blue: int) -> object:
        return self._call("self.robot.set_led_color", {"red": red, "green": green, "blue": blue})

    def set_volume(self, volume: int) -> object:
        return self._call("self.audio_speaker.set_volume", {"volume": volume})

    def cancel_pending(self) -> None:
        self.server.cancel_device_calls("self.robot.set_head_angles")

    def _call(self, name: str, arguments: dict[str, object]) -> object:
        return self.server.call_device_tool(name, arguments, timeout=self.timeout)


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
    ) -> None:
        self.pairing = pairing
        self.robot = robot
        self.audio_handler = audio_handler
        self.version = version
        self.server_name = server_name
        self.idle_timeout = idle_timeout
        self._server: Any = None
        self._sessions: dict[str, ServerConnection] = {}
        self._session_ids: dict[str, str] = {}
        self._session_credentials: dict[str, tuple[str, str]] = {}
        self._pending_device_calls: dict[str, tuple[asyncio.Future[object], str, str]] = {}
        self._early_device_replies: dict[str, dict[str, Any]] = {}
        self._device_call_deadlines: dict[str, float] = {}
        self._next_device_request_id = itertools.count(1)
        self._speaking: set[str] = set()
        self._source_requests: dict[str, list[float]] = {}
        self._session_ready = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self._loop = asyncio.get_running_loop()
        self._server = await serve(
            self.handle, host, port, max_size=2**20, ping_interval=20, ping_timeout=20
        )

    async def close(self) -> None:
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
                if not self._allow_pairing_request(source):
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
            await stale.close(code=1012, reason="Superseded by a reconnect from this Device-Id.")
        self._sessions[device_id] = websocket
        self._session_ids[device_id] = session_id
        self._session_credentials[device_id] = (client_id, token or "")
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
                    if state in {"start", "detect"}:
                        if data.get("mode") == "realtime":
                            await self._json(websocket, session_id, "tts", {"state": "start"})
                    elif state == "stop":
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
                self._session_credentials.pop(device_id, None)
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

    async def send_audio(self, device_id: str, frames: list[bytes]) -> None:
        """Send encoded 24 kHz Opus frames; codec and pacing belong upstream."""
        websocket = self._sessions.get(device_id)
        if self._sessions.get(device_id) is not websocket or not self._session_authorized(
            device_id
        ):
            raise PermissionError(
                "No authenticated active session exists for this Device-Id. Pair it and "
                "reconnect before sending audio."
            )
        self._speaking.add(device_id)
        await self._json(websocket, self._session_ids[device_id], "tts", {"state": "start"})
        interval = 0.06
        prebuffer = 3
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
                await websocket.send(frame)
        finally:
            self._speaking.discard(device_id)
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
        # StackChan firmware parses MCP request ids as numeric JSON-RPC ids.
        request_id = next(self._next_device_request_id)
        request_key = str(request_id)
        if self._loop is None:
            raise ConnectionError(
                "StackChan service is not running. Start the Bot body service and retry."
            )
        deadline = time.monotonic() + timeout
        self._device_call_deadlines[request_key] = deadline
        try:
            asyncio.run_coroutine_threadsafe(
                self._register_device_reply(request_key, device_id, name), self._loop
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

    async def _register_device_reply(self, request_key: str, device_id: str, name: str) -> None:
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
            raise RuntimeError("StackChan reported a tool error. Check the device and retry.")
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
