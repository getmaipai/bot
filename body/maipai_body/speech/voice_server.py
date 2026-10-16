"""VOICE-01: the robot's speech process, served over the shared voice contract.

``commons/spec/voice`` today defines two surfaces and this module serves
exactly those, byte-compatible with the hub's own sidecar so one client talks
to either:

* ``GET /health`` and ``POST /tts`` (multipart ``text``, streamed ``audio/wav``),
  the surface ``PocketTtsClient`` in ``spec/voice/ts/client.ts`` speaks.
* ``WS /api/stt/stream``: binary frames of little-endian float32 16 kHz mono
  PCM in, ``SttWireEvent`` JSON out (``ready``, ``vad``, ``final``,
  ``no_speech``, ``error``); a ``{"t":"end"}`` text frame flushes the utterance.

SPEC GAP, not worked around: the contract has no wake event and no endpoint
event, so the wake word and the follow-up window (``SpeechProcess``) stay
in-process on the robot until commons adds them. Nothing here invents a
second wire shape.
"""

from __future__ import annotations

import json
import logging
import math
import struct
import threading
from collections.abc import Callable
from email.parser import BytesParser
from email.policy import default as email_default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import numpy.typing as npt
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response
from websockets.sync.server import Server, ServerConnection, serve

from maipai_body.speech.capture import BLOCK_DURATION_S, BLOCK_SAMPLES, PRE_ROLL_S
from maipai_body.speech.engines import SttEngine, TtsEngine, VadEngine
from maipai_body.speech.process import MAX_UTTERANCE_S, TRAILING_SILENCE_S

logger = logging.getLogger("maipai_body.speech.voice_server")

STT_PATH = "/api/stt/stream"
SAMPLE_RATE = 16000
# Pocket TTS declares a placeholder data size in its header and consumers read
# only the format fields; this stream does the same because its length is
# unknown when the header is written.
_STREAM_DATA_SIZE = 0x7FFFFFFF
_MAX_FORM_BYTES = 64 * 1024


def wav_stream_header(sample_rate: int) -> bytes:
    return (
        b"RIFF"
        + struct.pack("<I", _STREAM_DATA_SIZE + 36)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", _STREAM_DATA_SIZE)
    )


def pcm16(samples: npt.NDArray[np.float32]) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def parse_form_text(content_type: str, body: bytes) -> str | None:
    """The ``text`` field of a multipart/form-data body, or ``None``."""
    message = BytesParser(policy=email_default).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + body
    )
    if not message.is_multipart():
        return None
    for part in message.iter_parts():
        if part.get_param("name", header="content-disposition") == "text":
            payload = part.get_payload(decode=True)
            return payload.decode("utf-8") if payload is not None else None
    return None


# -- TTS over HTTP -------------------------------------------------------------


def _tts_handler(tts: TtsEngine, lock: threading.Lock) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.0: the body ends when the connection closes, which is what a
        # stream of unknown length needs and what ``fetch`` reads without fuss.
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            logger.debug("tts http: " + format, *args)

        def _reply(self, status: int, payload: dict[str, str]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._reply(200, {"status": "healthy"})
            else:
                self._reply(404, {"error": f"no route {self.path}; use /health or /tts"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/tts":
                self._reply(404, {"error": f"no route {self.path}; use /health or /tts"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > _MAX_FORM_BYTES:
                self._reply(400, {"error": "send a multipart form with a text field"})
                return
            text = parse_form_text(self.headers.get("Content-Type", ""), self.rfile.read(length))
            if not text or not text.strip():
                self._reply(400, {"error": "the form has no text to speak; add a text field"})
                return
            with lock:  # one engine, one sentence at a time
                try:
                    segments = tts.synthesize(text)
                    first = next(iter(segments), None)
                except Exception:  # noqa: BLE001 - reported to the caller, not the log's payload
                    logger.exception("synthesis failed")
                    self._reply(500, {"error": "the voice failed to speak; try again"})
                    return
                if first is None:
                    self._reply(500, {"error": "the voice produced no audio; try other text"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.end_headers()
                try:
                    self.wfile.write(wav_stream_header(first.sample_rate))
                    self.wfile.write(pcm16(first.samples))
                    self.wfile.flush()
                    for segment in segments:
                        self.wfile.write(pcm16(segment.samples))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return  # the listener hung up; nothing more to say
                except Exception:  # noqa: BLE001
                    logger.exception("synthesis failed mid-stream")

    return Handler


class TtsHttpServer:
    def __init__(self, tts: TtsEngine, host: str = "127.0.0.1", port: int = 0) -> None:
        handler = _tts_handler(tts, threading.Lock())
        self._server = ThreadingHTTPServer((host, port), handler)
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


# -- STT over WebSocket --------------------------------------------------------


class SttSession:
    """VAD, pre-roll, endpointing and transcription for one streamed utterance.

    The same rules ``SpeechProcess`` applies to the microphone (0.3 s pre-roll
    kept while waiting, 0.7 s trailing silence ends the utterance, 12 s hard
    cap), but fed from the wire. ``send`` receives ``SttWireEvent`` dicts."""

    def __init__(self, vad: VadEngine, stt: SttEngine, send: Callable[[dict], None]) -> None:
        self._vad = vad
        self._stt = stt
        self._send = send
        self._preroll_blocks = max(1, math.ceil(PRE_ROLL_S / BLOCK_DURATION_S))
        self._rest = np.zeros(0, np.float32)
        self._reset()

    def _reset(self) -> None:
        self._buffer: list[npt.NDArray[np.float32]] = []
        self._speaking = False
        self._silence_s = 0.0
        self._elapsed_s = 0.0
        self._vad.reset()

    def feed(self, pcm: npt.NDArray[np.float32]) -> None:
        data = np.concatenate([self._rest, pcm])
        whole = len(data) // BLOCK_SAMPLES * BLOCK_SAMPLES
        self._rest = data[whole:]
        for i in range(0, whole, BLOCK_SAMPLES):
            self._block(data[i : i + BLOCK_SAMPLES])

    def _block(self, block: npt.NDArray[np.float32]) -> None:
        self._buffer.append(block)
        self._elapsed_s += BLOCK_DURATION_S
        if self._vad.is_speech(block):
            self._silence_s = 0.0
            if not self._speaking:
                self._speaking = True
                self._send({"t": "vad", "speaking": True, "rms": _rms(block)})
        else:
            self._silence_s += BLOCK_DURATION_S
            if not self._speaking and len(self._buffer) > self._preroll_blocks:
                del self._buffer[: len(self._buffer) - self._preroll_blocks]
        if self._speaking and (
            self._silence_s >= TRAILING_SILENCE_S or self._elapsed_s >= MAX_UTTERANCE_S
        ):
            self._finish()

    def end(self) -> None:
        """The client's ``{"t":"end"}``: flush now instead of waiting for silence."""
        if self._speaking:
            self._finish()
        else:
            self._send({"t": "no_speech"})
            self._reset()

    def _finish(self) -> None:
        pcm = np.concatenate(self._buffer) if self._buffer else np.zeros(0, np.float32)
        self._send({"t": "vad", "speaking": False, "rms": 0.0})
        try:
            text = (self._stt.transcribe(pcm, SAMPLE_RATE) or "").strip()
        except Exception:  # noqa: BLE001
            logger.exception("transcription failed")
            self._send({"t": "error", "v": "speech to text failed; say it again"})
        else:
            self._send({"t": "final", "v": text} if text else {"t": "no_speech"})
        self._reset()


def _rms(block: npt.NDArray[np.float32]) -> float:
    return float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))


class SttWsServer:
    def __init__(
        self,
        make_session: Callable[[Callable[[dict], None]], SttSession],
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self._make_session = make_session
        self._host, self._port = host, port
        self._server: Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        assert self._server is not None, "start() first"
        host, port = self._server.socket.getsockname()[:2]
        return f"http://{host}:{port}"

    def _route(self, connection: ServerConnection, request: Request) -> Response | None:
        if request.path != STT_PATH:
            return connection.respond(404, f"no route {request.path}; use {STT_PATH}\n")
        return None

    def _handle(self, ws: ServerConnection) -> None:
        def send(event: dict) -> None:
            ws.send(json.dumps(event))

        session = self._make_session(send)
        send({"t": "ready"})
        try:
            for message in ws:
                if isinstance(message, bytes):
                    usable = len(message) // 4 * 4
                    session.feed(np.frombuffer(message[:usable], dtype="<f4").astype(np.float32))
                elif _is_end(message):
                    session.end()
        except ConnectionClosed:
            return

    def start(self) -> None:
        self._server = serve(self._handle, self._host, self._port, process_request=self._route)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=2)


def _is_end(message: str) -> bool:
    try:
        return json.loads(message).get("t") == "end"
    except (ValueError, AttributeError):
        return False
