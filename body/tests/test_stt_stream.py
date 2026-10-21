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


class _NumberedMic:
    """An AudioIO whose Nth buffer is one block filled with the value N/10000,
    so a received frame says which captured block it is."""

    def __init__(self) -> None:
        self.next_index = 0

    def start_recording(self) -> None: ...

    def stop_recording(self) -> None: ...

    def get_input_audio_samplerate(self) -> int:
        return 16000

    def get_audio_sample(self):
        value = self.next_index / 10000.0
        self.next_index += 1
        return np.full((512, 1), value, dtype=np.float32)


def test_only_audio_after_the_wake_leaves_the_body_and_none_after_the_final(stt_server):
    """RM-04: nothing ambient leaves the body. The bytes sent are the blocks captured
    from the wake to the hub's final: none from the wake-listening stretch, and none
    polled after the session ended."""
    server, handler = stt_server(
        [(0.4, {"t": "vad", "speaking": True}), (0.2, {"t": "final", "v": "ok"})]
    )
    client = SttStreamClient(f"http://127.0.0.1:{server.socket.getsockname()[1]}", "cookie-abc")
    mic = _NumberedMic()
    capture = AudioCapture(mic)
    capture.start()
    for _ in range(200):  # the wake-listening stretch: scored locally, never sent
        capture.poll_blocks()
    first_after_wake = mic.next_index

    result = client.run(capture)

    assert result.kind == "final"
    sent = [
        int(round(float(np.frombuffer(frame, dtype=np.float32)[0]) * 10000))
        for frame in handler.received_binary
    ]
    assert len(sent) > 0
    assert min(sent) >= first_after_wake  # nothing from before the wake
    assert sent == list(range(first_after_wake, first_after_wake + len(sent)))  # the span, in order
    assert mic.next_index == first_after_wake + len(sent)  # nothing polled or sent after the final


def test_speech_starting_at_the_deadline_is_not_cut_off_by_an_early_end(stt_server):
    """The hub vad trails the audio; a grace past the deadline comes before giving up."""
    import time

    from maipai_body.speech import stt_stream

    server, handler = stt_server(
        [(0.35, {"t": "vad", "speaking": True, "rms": 0.1}), (0.1, {"t": "final", "v": "hi"})]
    )
    client = SttStreamClient(
        f"http://127.0.0.1:{server.socket.getsockname()[1]}", "cookie-abc", wake_patience_s=0.2
    )
    capture, _ = _capture_with_fixture()
    assert stt_stream._GIVE_UP_GRACE_S >= 0.5
    started = time.monotonic()
    result = client.run(capture)
    assert result.kind == "final" and result.text == "hi"
    assert {"t": "end"} not in handler.received_text
    assert time.monotonic() - started < 3


def test_the_wait_for_the_final_after_end_covers_a_slow_transcription():
    from maipai_body.speech import stt_stream

    assert stt_stream._FINAL_WAIT_S >= 10.0


def test_a_quiet_listen_stops_waiting_when_the_hub_never_answers_end(stt_server):
    """The hub sends nothing for `end` when nobody spoke; the host must not wait the full 12 s."""
    import time

    server, handler = stt_server([(8.0, "close")])
    client = SttStreamClient(
        f"http://127.0.0.1:{server.socket.getsockname()[1]}", "cookie-abc", wake_patience_s=0.2
    )
    capture, _ = _capture_with_fixture()
    started = time.monotonic()
    result = client.run(capture)
    assert result.kind == "timeout"
    assert {"t": "end"} in handler.received_text
    assert time.monotonic() - started < 4.0


def test_speech_in_flight_at_give_up_keeps_the_long_wait(stt_server):
    """A vad speaking message that lands after the end request means the hub will finalize."""
    server, _handler = stt_server(
        [(0.9, {"t": "vad", "speaking": True, "rms": 0.1}), (2.0, {"t": "final", "v": "hello"})]
    )
    client = SttStreamClient(
        f"http://127.0.0.1:{server.socket.getsockname()[1]}", "cookie-abc", wake_patience_s=0.2
    )
    capture, _ = _capture_with_fixture()
    result = client.run(capture)
    assert result.kind == "final" and result.text == "hello"
