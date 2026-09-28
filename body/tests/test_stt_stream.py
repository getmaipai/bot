"""G3+G6 (send side)'s own acceptance: a real local WebSocket server
standing in for the hub's own /api/stt/stream session (RM-03's own
"a small server in the test" pattern), so the wire protocol itself -
binary audio frames, JSON control frames, the wake-patience timeout -
is exercised for real, not mocked."""

from __future__ import annotations

import json
import threading

import numpy as np
import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.speech.capture import AudioCapture
from maipai_body.speech.stt_stream import SttStreamClient, SttStreamError


class _ScriptedSttServer:
    """Sends `{t:"ready"}` on connect, then whatever `script` says (a
    list of (delay_s, message) pairs, message either a dict to send as
    JSON or the literal string "close" to close the connection).
    Records every binary frame and every text message it receives."""

    def __init__(self, script: list[tuple[float, dict | str]]) -> None:
        self.script = script
        self.received_binary: list[bytes] = []
        self.received_text: list[dict] = []
        self.cookie_header: str | None = None

    def __call__(self, ws) -> None:
        self.cookie_header = ws.request.headers.get("Cookie")
        ws.send(json.dumps({"t": "ready"}))
        stop = threading.Event()

        def recv_loop():
            try:
                while not stop.is_set():
                    message = ws.recv(timeout=0.1)
                    if isinstance(message, bytes):
                        self.received_binary.append(message)
                    else:
                        self.received_text.append(json.loads(message))
            except TimeoutError:
                pass
            except Exception:
                pass

        recv_thread = threading.Thread(target=recv_loop, daemon=True)
        recv_thread.start()

        for delay_s, message in self.script:
            stop.wait(delay_s)
            if message == "close":
                break
            ws.send(json.dumps(message))
        stop.wait(0.2)  # let any last frames arrive before closing
        stop.set()
        recv_thread.join(timeout=1)


@pytest.fixture
def stt_server():
    started = []

    def start(script: list[tuple[float, dict | str]]):
        handler = _ScriptedSttServer(script)
        server = serve(handler, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append(server)
        return server, handler

    yield start
    for server in started:
        server.shutdown()


def _capture_with_fixture(seconds: float = 3.0) -> tuple[AudioCapture, FakeReachyMiniClient]:
    import tempfile
    import wave
    from pathlib import Path

    sample_rate = 16000
    n = int(seconds * sample_rate)
    t = np.arange(n) / sample_rate
    tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    ints = (tone * 32767).astype(np.int16)
    tmp = Path(tempfile.mkdtemp()) / "tone.wav"
    with wave.open(str(tmp), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(ints.tobytes())
    client = FakeReachyMiniClient(microphone_wav=tmp)
    capture = AudioCapture(client)
    capture.start()
    return capture, client


def test_final_transcript_ends_the_stream(stt_server):
    server, handler = stt_server(
        [(0.05, {"t": "vad", "speaking": True}), (0.1, {"t": "final", "v": "hello there"})]
    )
    client = SttStreamClient(f"http://127.0.0.1:{server.socket.getsockname()[1]}", "cookie-abc")
    capture, _ = _capture_with_fixture()

    result = client.run(capture)

    assert result.kind == "final"
    assert result.text == "hello there"


def test_no_speech_ends_the_stream(stt_server):
    server, handler = stt_server([(0.1, {"t": "no_speech"})])
    client = SttStreamClient(f"http://127.0.0.1:{server.socket.getsockname()[1]}", "cookie-abc")
    capture, _ = _capture_with_fixture()

    result = client.run(capture)

    assert result.kind == "no_speech"


def test_a_session_error_ends_the_stream(stt_server):
    server, handler = stt_server([(0.1, {"t": "error", "v": "malformed audio frame"})])
    client = SttStreamClient(f"http://127.0.0.1:{server.socket.getsockname()[1]}", "cookie-abc")
    capture, _ = _capture_with_fixture()

    result = client.run(capture)

    assert result.kind == "error"
    assert result.error == "malformed audio frame"


def test_wake_patience_expires_and_sends_end(stt_server):
    """The stand-in never speaks - the timeout must fire and the client
    must send {t:"end"} before giving up, matching the revised design's
    own acceptance."""
    server, handler = stt_server([(2.0, "close")])  # nothing before the client's own timeout
    client = SttStreamClient(
        f"http://127.0.0.1:{server.socket.getsockname()[1]}", "cookie-abc", wake_patience_s=0.2
    )
    capture, _ = _capture_with_fixture()

    result = client.run(capture)

    assert result.kind == "timeout"
    assert {"t": "end"} in handler.received_text


def test_vad_speaking_cancels_the_wake_patience_timer(stt_server):
    """A real vad:true arriving well before the (short, test-scale)
    wake-patience window must keep the stream open past it - proven by
    waiting past the window and then still getting a real final."""
    server, handler = stt_server(
        [(0.05, {"t": "vad", "speaking": True}), (0.4, {"t": "final", "v": "took a while"})]
    )
    client = SttStreamClient(
        f"http://127.0.0.1:{server.socket.getsockname()[1]}", "cookie-abc", wake_patience_s=0.2
    )
    capture, _ = _capture_with_fixture()

    result = client.run(capture)

    assert result.kind == "final"
    assert result.text == "took a while"
    # The timeout's own {t:"end"} must NOT have been sent - vad cancelled it.
    assert {"t": "end"} not in handler.received_text


def test_audio_blocks_are_forwarded_as_binary_frames(stt_server):
    server, handler = stt_server([(0.3, {"t": "final", "v": "ok"})])
    client = SttStreamClient(f"http://127.0.0.1:{server.socket.getsockname()[1]}", "cookie-abc")
    capture, _ = _capture_with_fixture(seconds=1.0)

    client.run(capture)

    assert len(handler.received_binary) > 0
    for frame in handler.received_binary:
        assert len(frame) % 4 == 0  # a whole number of float32 samples


def test_the_session_cookie_is_sent_on_the_handshake(stt_server):
    server, handler = stt_server([(0.1, {"t": "no_speech"})])
    client = SttStreamClient(
        f"http://127.0.0.1:{server.socket.getsockname()[1]}", "my-cookie-value"
    )
    capture, _ = _capture_with_fixture()

    client.run(capture)

    assert handler.cookie_header == "session=my-cookie-value"


def test_a_dropped_connection_raises_stt_stream_error():
    client = SttStreamClient("http://127.0.0.1:1", "cookie-abc")  # nothing listens here
    capture, _ = _capture_with_fixture()

    with pytest.raises(SttStreamError):
        client.run(capture)


def test_give_up_treats_a_closed_connection_on_send_as_a_timeout_not_an_error():
    """The review-caught bug: only recv() was guarded against
    ConnectionClosed, not the send() right before it - a hub closing
    the connection at that exact moment raised an unhandled
    SttStreamError instead of the intended graceful timeout."""

    class _ClosesOnSend:
        def send(self, data):
            raise ConnectionClosed(None, None)

    client = SttStreamClient("http://127.0.0.1:1", "cookie-abc")

    result = client._give_up(_ClosesOnSend())

    assert result.kind == "timeout"


def test_empty_session_cookie_raises_immediately():
    with pytest.raises(ValueError, match="session_cookie"):
        SttStreamClient("http://127.0.0.1:1", "")
