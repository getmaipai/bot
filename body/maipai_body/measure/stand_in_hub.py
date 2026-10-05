"""A bench stand-in for the hub's robot-facing routes, with a switch for the link.

One stand-in serves everything the body calls on a hub, over real
sockets, so the real clients run against it unmodified:

- pairing: ``POST /api/auth/quick-connect/code``, ``GET .../poll``,
  ``POST /api/auth/devices/redeem`` (answers with the session cookie),
  for ``HubLinkClient``;
- the turn stream ``POST /api/turn/stream`` (``turn_meta``, ``signal``,
  an optional scripted ``plan``, ``delta``, ``done``) and
  ``POST /api/turn/{id}/cancel``, which ends an in-flight turn with an
  ``error`` event, for ``TurnClient``;
- the ``stt`` websocket and ``POST /api/tts``;
- ``PUT /api/devices/me/state``, every frame kept in ``state_frames``;
- ``GET /api/biometric-prints/sync`` (``prints``) for ``PrintSync``;
- ``GET /api/devices/me/hub-endpoints`` (``endpoints``);
- a mute command channel, ``GET /api/devices/me/commands?after=N``, only
  with ``mute_channel=True``.

Not verified against the hub (``home`` is a sibling repo this stand-in
was written without): the ``plan`` event body, the ``hub-endpoints``
response shape and the whole command channel, whose real transport is
still undecided (ROBOT-MUTE-01, a settings key or a device-command
channel). They are the shapes the body's design notes name, labelled
here so no test mistakes them for the hub's contract. Addresses are
RFC 5737 documentation addresses and ``example.com`` names, never real
ones. Set ``require_auth=True`` to make the authenticated routes
answer 401 without the session cookie.

The link is the point. ``cut(mode)`` takes the whole hub down at once:

- ``reset``: every open connection is torn down and new ones are refused
  at once (a router that drops the association and says so).
- ``blackhole``: connections stay open and nothing is answered (the usual
  Wi-Fi loss: packets vanish, so a client finds out only by its own timeout).

``fail_next(route, after=N, mode=...)`` arms a one-shot fault on the next
response of a route: it fires after ``N`` events (turn: meta-and-signal,
reply text, done; tts: one 1 KiB chunk each; stt: before ``ready``), and
``reset`` or ``blackhole`` take the hub down at that moment, while
``truncate`` just ends the stream cleanly without its terminal event.
"""

from __future__ import annotations

import http.server
import json
import socket
import struct
import threading
import time
import wave
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import numpy as np
from websockets.sync.server import serve

_TTS_CHUNK_BYTES = 1024


@dataclass
class _Fault:
    route: str
    after: int
    mode: str  # "reset" | "blackhole" | "truncate"


def make_wav_bytes(seconds: float, sample_rate: int = 24_000) -> bytes:
    """A mono 16-bit sine tone, the shape the hub's tts route streams."""
    n = int(seconds * sample_rate)
    t = np.arange(n) / sample_rate
    tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    ints = (tone * 32767).astype(np.int16)
    buf = BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(ints.tobytes())
    return buf.getvalue()


def _reset(sock: socket.socket) -> None:
    """Tear a connection down so the peer sees a reset, not a polite close."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


class StandInHub:
    def __init__(
        self,
        *,
        reply_text: str = "hello back",
        stt_text: str = "hello maipai",
        tts_seconds: float = 0.3,
        event_delay_s: float = 0.02,
        plan_event: dict | None = None,
        require_auth: bool = False,
        approve_after_polls: int = 0,
        mute_channel: bool = False,
    ) -> None:
        self.reply_text = reply_text
        self.stt_text = stt_text
        self.tts_seconds = tts_seconds
        self.event_delay_s = event_delay_s
        self.plan_event = plan_event
        self.require_auth = require_auth
        self.approve_after_polls = approve_after_polls
        self.mute_channel = mute_channel
        self.device_token = "device-token-bench"
        self.session_cookie = "session-bench"
        self.paired_requests: list[dict] = []
        self.redeemed_tokens: list[str] = []
        self.cancelled_turns: list[str] = []
        self.stt_handshakes: list[dict[str, str | None]] = []
        self.state_frames: list[dict] = []
        self.prints: list[dict] = []
        self.endpoints: list[dict] = [
            {"url": "http://192.0.2.10:3000", "kind": "lan", "priority": 10},
            {"url": "https://hub.tailnet.example.com", "kind": "overlay", "priority": 60},
        ]
        self._commands: list[dict] = []
        self._polls: dict[str, int] = {}
        self._in_flight: set[str] = set()
        self._cancel_flags: set[str] = set()
        self.state_reports: list[float] = []
        self.tts_requests: list[str] = []
        self.loss_at: float | None = None
        self.restored_at: float | None = None
        self.fault_fired_at: float | None = None
        self._down: str | None = None
        self._released = threading.Event()
        self._lock = threading.Lock()
        self._active: set[socket.socket] = set()
        self._fault: _Fault | None = None
        self._http: http.server.ThreadingHTTPServer | None = None
        self._ws = None
        self.http_url = ""
        self.stt_url = ""

    # -- lifecycle --

    def start(self) -> None:
        hub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format, *args):  # noqa: A002 - stdlib signature
                pass

            def setup(self) -> None:
                super().setup()
                hub._track(self.connection)

            def finish(self) -> None:
                hub._untrack(self.connection)
                try:
                    super().finish()
                except Exception:
                    pass

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
                if not self._gate():
                    return
                url = urlparse(self.path)
                if url.path == "/api/auth/quick-connect/poll":
                    token = parse_qs(url.query).get("poll_token", [""])[0]
                    self._json(hub._poll(token))
                elif not self._authed():
                    return
                elif url.path == "/api/biometric-prints/sync":
                    self._json({"prints": hub.prints})
                elif url.path == "/api/devices/me/hub-endpoints":
                    self._json({"endpoints": hub.endpoints})
                elif url.path == "/api/devices/me/commands" and hub.mute_channel:
                    after = int(parse_qs(url.query).get("after", ["0"])[0])
                    self._json({"commands": [c for c in hub._commands if c["seq"] > after]})
                elif url.path.startswith("/api/devices/me/") or url.path.startswith("/api/"):
                    self._json({"error": "not found"}, status=404)
                else:
                    self._plain(b"ok")

            def do_PUT(self) -> None:  # noqa: N802
                body = self._read_body()
                if self._gate() and self._authed():
                    if self.path == "/api/devices/me/state":
                        hub.state_frames.append(json.loads(body or b"{}"))
                    hub.state_reports.append(time.monotonic())
                    self._plain(b"{}")

            def do_POST(self) -> None:  # noqa: N802
                body = self._read_body()
                if not self._gate():
                    return
                if self.path == "/api/auth/quick-connect/code":
                    self._json(hub._issue_code(json.loads(body or b"{}")))
                elif self.path == "/api/auth/devices/redeem":
                    token = json.loads(body or b"{}").get("token", "")
                    if token != hub.device_token:
                        self._json({"error": "unknown token"}, status=401)
                    else:
                        hub.redeemed_tokens.append(token)
                        self._json(
                            {"success": True},
                            headers={"Set-Cookie": f"session={hub.session_cookie}; Path=/"},
                        )
                elif not self._authed():
                    return
                elif self.path == "/api/turn/stream":
                    hub._serve_turn(self)
                elif self.path.startswith("/api/turn/") and self.path.endswith("/cancel"):
                    turn_id = self.path.split("/")[3]
                    self._json({"cancelled": hub._cancel(turn_id)})
                elif self.path == "/api/tts":
                    hub.tts_requests.append(json.loads(body or b"{}").get("text", ""))
                    hub._serve_tts(self)
                else:
                    self._plain(b"{}")

            def _authed(self) -> bool:
                if not hub.require_auth:
                    return True
                if f"session={hub.session_cookie}" in (self.headers.get("Cookie") or ""):
                    return True
                self._json({"error": "unauthorized"}, status=401)
                return False

            def _json(self, body: dict, *, status: int = 200, headers: dict | None = None) -> None:
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(payload)

            def _read_body(self) -> bytes:
                return self.rfile.read(int(self.headers.get("Content-Length", 0)))

            def _gate(self) -> bool:
                """False once the link is down; a blackhole holds here until it lifts."""
                if hub._down is None:
                    return True
                if hub._down == "blackhole":
                    hub._released.wait()
                self.close_connection = True
                _reset(self.connection)
                return False

            def _plain(self, payload: bytes) -> None:
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def start_chunked(self, content_type: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

            def chunk(self, data: bytes) -> None:
                self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()

            def end_chunked(self) -> None:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()

        class Server(http.server.ThreadingHTTPServer):
            def handle_error(self, request, client_address) -> None:
                pass  # a torn-down connection is the point, not a traceback

        self._http = Server(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._http.serve_forever, daemon=True).start()
        self.http_url = f"http://127.0.0.1:{self._http.server_port}"

        self._ws = serve(self._serve_stt, "127.0.0.1", 0)
        threading.Thread(target=self._ws.serve_forever, daemon=True).start()
        self.stt_url = f"http://127.0.0.1:{self._ws.socket.getsockname()[1]}"

    def stop(self) -> None:
        self._released.set()
        with self._lock:
            active = list(self._active)
        for sock in active:
            _reset(sock)
        if self._http is not None:
            self._http.shutdown()
            self._http.server_close()
        if self._ws is not None:
            self._ws.shutdown()

    def __enter__(self) -> StandInHub:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- the link --

    def cut(self, mode: str = "reset") -> None:
        if mode not in ("reset", "blackhole"):
            raise ValueError(f"mode must be 'reset' or 'blackhole', not {mode!r}")
        self.loss_at = time.monotonic()
        self.restored_at = None
        self._released.clear()
        self._down = mode
        if mode == "reset":
            with self._lock:
                active = list(self._active)
            for sock in active:
                _reset(sock)

    def restore(self) -> None:
        self._down = None
        self.restored_at = time.monotonic()
        self._released.set()  # lets any blackholed connection go

    def fail_next(self, route: str, *, after: int, mode: str) -> None:
        if route not in ("turn", "tts", "stt"):
            raise ValueError(f"unknown route {route!r}")
        if mode not in ("reset", "blackhole", "truncate"):
            raise ValueError(f"unknown fault mode {mode!r}")
        self._fault = _Fault(route=route, after=after, mode=mode)

    def send_mute(self, muted: bool) -> None:
        """Queue a mute command for the body's next poll of the command channel."""
        if not self.mute_channel:
            raise RuntimeError("the command channel is off: construct with mute_channel=True")
        with self._lock:
            self._commands.append({"seq": len(self._commands) + 1, "type": "mute", "muted": muted})

    # -- internals --

    def _issue_code(self, request: dict) -> dict:
        self.paired_requests.append(request)
        poll_token = f"poll-{len(self.paired_requests)}"
        self._polls[poll_token] = 0
        return {"code": "AB12CD", "poll_token": poll_token}

    def _poll(self, poll_token: str) -> dict:
        seen = self._polls.get(poll_token)
        if seen is None:
            return {"status": "expired"}
        self._polls[poll_token] = seen + 1
        if seen < self.approve_after_polls:
            return {"status": "pending"}
        return {
            "status": "approved",
            "device_token": self.device_token,
            "expires_at": "2099-01-01",
        }

    def _cancel(self, turn_id: str) -> bool:
        with self._lock:
            if turn_id not in self._in_flight:
                return False
            self._cancel_flags.add(turn_id)
            self.cancelled_turns.append(turn_id)
            return True

    def _track(self, sock: socket.socket) -> None:
        with self._lock:
            self._active.add(sock)

    def _untrack(self, sock: socket.socket) -> None:
        with self._lock:
            self._active.discard(sock)

    def _take_fault(self, route: str) -> _Fault | None:
        fault = self._fault
        if fault is not None and fault.route == route:
            self._fault = None
            return fault
        return None

    def _fire(self, fault: _Fault) -> bool:
        """Apply a fault; True when the stream is over for this response."""
        self.fault_fired_at = time.monotonic()
        if fault.mode == "truncate":
            return False  # the caller ends the stream cleanly
        self.cut(fault.mode)
        if fault.mode == "blackhole":
            self._released.wait()
        return True

    def _serve_turn(self, handler) -> None:
        fault = self._take_fault("turn")
        turn_id = "turn-bench"
        first_unit = [
            {"type": "turn_meta", "conversation_id": "conv-bench", "turn_id": turn_id},
            {
                "type": "signal",
                "signal": {
                    "primary_act": "inform",
                    "expressed_emotion": "happiness",
                    "emotion_intensity": "moderate",
                },
            },
        ]
        if self.plan_event is not None:
            first_unit.append(self.plan_event)
        units = [
            first_unit,
            [{"type": "delta", "text": self.reply_text}],
            [{"type": "done", "value": {}}],
        ]
        started = False
        with self._lock:
            self._in_flight.add(turn_id)
        try:
            for index, unit in enumerate(units):
                if fault is not None and index == fault.after:
                    if self._fire(fault):
                        handler.close_connection = True
                        return
                    handler.end_chunked()
                    return
                if not started:
                    handler.start_chunked("application/x-ndjson")
                    started = True
                if turn_id in self._cancel_flags:
                    cancelled = {"type": "error", "code": "turn_cancelled"}
                    handler.chunk((json.dumps(cancelled) + "\n").encode())
                    break
                handler.chunk("".join(json.dumps(line) + "\n" for line in unit).encode())
                time.sleep(self.event_delay_s)
        finally:
            with self._lock:
                self._in_flight.discard(turn_id)
                self._cancel_flags.discard(turn_id)
        handler.end_chunked()

    def _serve_tts(self, handler) -> None:
        fault = self._take_fault("tts")
        data = make_wav_bytes(self.tts_seconds)
        handler.start_chunked("audio/wav")
        for index, start in enumerate(range(0, len(data), _TTS_CHUNK_BYTES)):
            if fault is not None and index == fault.after:
                if self._fire(fault):
                    handler.close_connection = True
                    return
                handler.end_chunked()
                return
            handler.chunk(data[start : start + _TTS_CHUNK_BYTES])
            time.sleep(self.event_delay_s)
        handler.end_chunked()

    def _serve_stt(self, ws) -> None:
        self._track(ws.socket)
        try:
            fault = self._take_fault("stt")
            self.stt_handshakes.append(
                {"path": ws.request.path, "cookie": ws.request.headers.get("Cookie")}
            )
            if self._down is not None:
                if self._down == "blackhole":
                    self._released.wait()
                _reset(ws.socket)
                return
            if fault is not None and fault.after == 0:
                if self._fire(fault):
                    _reset(ws.socket)
                else:
                    ws.close()
                return
            ws.send(json.dumps({"t": "ready"}))
            time.sleep(0.05)
            ws.send(json.dumps({"t": "vad", "speaking": True}))
            time.sleep(0.05)
            ws.send(json.dumps({"t": "final", "v": self.stt_text}))
            time.sleep(0.2)  # let the client's own audio sends land before closing
        finally:
            self._untrack(ws.socket)
