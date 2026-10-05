"""A bench stand-in for the hub's robot-facing routes, with a switch for the link.

Serves what the body's three hub clients call (the turn stream, the tts
stream, the stt websocket) plus the device state route, over real
sockets, so the real ``TurnClient``, ``TtsPlaybackClient``,
``SttStreamClient`` and ``StateReporter`` run against it unmodified. The
scripted content is the same shape the live run-loop test used before it
moved here.

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
    ) -> None:
        self.reply_text = reply_text
        self.stt_text = stt_text
        self.tts_seconds = tts_seconds
        self.event_delay_s = event_delay_s
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
                if self._gate():
                    self._plain(b"ok")

            def do_PUT(self) -> None:  # noqa: N802
                self._read_body()
                if self._gate():
                    hub.state_reports.append(time.monotonic())
                    self._plain(b"{}")

            def do_POST(self) -> None:  # noqa: N802
                body = self._read_body()
                if not self._gate():
                    return
                if self.path == "/api/turn/stream":
                    hub._serve_turn(self)
                elif self.path == "/api/tts":
                    hub.tts_requests.append(json.loads(body or b"{}").get("text", ""))
                    hub._serve_tts(self)
                else:
                    self._plain(b"{}")

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

    # -- internals --

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
        units = [
            [
                {"type": "turn_meta", "conversation_id": "conv-bench", "turn_id": "turn-bench"},
                {
                    "type": "signal",
                    "signal": {
                        "primary_act": "inform",
                        "expressed_emotion": "happiness",
                        "emotion_intensity": "moderate",
                    },
                },
            ],
            [{"type": "delta", "text": self.reply_text}],
            [{"type": "done", "value": {}}],
        ]
        started = False
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
            handler.chunk("".join(json.dumps(line) + "\n" for line in unit).encode())
            time.sleep(self.event_delay_s)
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
