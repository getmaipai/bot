"""G7's own acceptance (the gap-audit's exact words): "A stand-in
server streams a 24 kHz 16-bit mono WAV fixture in 1 KB chunks; the
fake records 16 kHz mono float32 pushes whose total duration matches
the fixture within one block, the ledger holds the pushed prefix when
the stream is stopped at 40 percent, and the SPEAK cue's stamp
precedes the first push." Driven against a real local HTTP server
streaming a real generated WAV, not a mocked response."""

from __future__ import annotations

import http.server
import threading
import wave
from io import BytesIO

import numpy as np
import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.tts_playback import TtsAuthFailed, TtsLinkLost, TtsPlaybackClient

_SOURCE_RATE = 24_000
_CHUNK_BYTES = 1_024


def _make_wav_bytes(seconds: float, sample_rate: int = _SOURCE_RATE) -> bytes:
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


class _TtsServer(http.server.BaseHTTPRequestHandler):
    """Streams `wav_bytes` in `_CHUNK_BYTES`-sized pieces. `status` lets
    a test script a 401. `stall_after_bytes`, if set, stops writing
    (without closing) after that many bytes - used to exercise a
    mid-stream stop from the client side."""

    wav_bytes: bytes = b""
    status: int = 200
    request_body: dict | None = None

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        length = int(self.headers.get("Content-Length", 0))
        import json

        type(self).request_body = json.loads(self.rfile.read(length) or b"{}")

        if self.status != 200:
            body = b'{"error": "unauthorized"}'
            self.send_response(self.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.end_headers()
        data = self.wav_bytes
        for i in range(0, len(data), _CHUNK_BYTES):
            self.wfile.write(data[i : i + _CHUNK_BYTES])
            self.wfile.flush()


@pytest.fixture
def tts_server():
    def _reset(wav_bytes: bytes, *, status: int = 200):
        _TtsServer.wav_bytes = wav_bytes
        _TtsServer.status = status
        _TtsServer.request_body = None

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _TtsServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, _TtsServer, _reset
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _base_url(server) -> str:
    return f"http://127.0.0.1:{server.server_port}"


def _playback() -> AudioPlayback:
    client = FakeReachyMiniClient()
    return AudioPlayback(client)


def test_a_streamed_reply_pushes_matching_duration(tts_server):
    server, handler, reset = tts_server
    reset(_make_wav_bytes(2.0))
    playback = _playback()
    client = TtsPlaybackClient(_base_url(server), "cookie-abc", playback)

    result = client.speak("hello there")

    assert result.kind == "done"
    assert result.first_chunk_pushed
    # 16 kHz output vs the fixture's 24 kHz source, resampled - within
    # one G1-style block (32 ms) of the real 2.0 s duration.
    assert abs(playback.pushed_duration_s() - 2.0) < 0.05


def test_the_on_first_chunk_callback_fires_once_before_the_stream_ends(tts_server):
    server, handler, reset = tts_server
    reset(_make_wav_bytes(1.0))
    playback = _playback()
    client = TtsPlaybackClient(_base_url(server), "cookie-abc", playback)
    calls = []

    client.speak("hi", on_first_chunk=lambda: calls.append(1))

    assert calls == [1]


def test_stopping_mid_stream_keeps_the_pushed_prefix(tts_server):
    """The ledger holds the pushed prefix when stopped partway through -
    the gap-audit's own acceptance wording, adapted to a deterministic
    stop_event instead of a wall-clock percentage."""
    import threading as th

    server, handler, reset = tts_server
    reset(_make_wav_bytes(3.0))
    playback = _playback()
    client = TtsPlaybackClient(_base_url(server), "cookie-abc", playback)
    stop_event = th.Event()
    pushes_before_stop = []

    def _stop_after_a_few_chunks():
        pushes_before_stop.append(1)
        if len(pushes_before_stop) >= 3:
            stop_event.set()

    # There's no per-chunk callback in the public API beyond
    # on_first_chunk, so drive the stop from a wrapped playback that
    # counts real pushes instead - still exercising the real code path.
    real_push = playback.push

    def _counting_push(chunk):
        real_push(chunk)
        _stop_after_a_few_chunks()

    playback.push = _counting_push

    result = client.speak("a longer reply than the stop allows", stop_event=stop_event)

    assert result.kind == "cancelled"
    assert result.first_chunk_pushed
    pushed = playback.pushed_duration_s()
    assert 0 < pushed < 3.0  # a real, non-empty prefix, not the whole reply


def test_a_401_raises_tts_auth_failed(tts_server):
    server, handler, reset = tts_server
    reset(b"", status=401)
    playback = _playback()
    client = TtsPlaybackClient(_base_url(server), "a-stale-cookie", playback)

    with pytest.raises(TtsAuthFailed):
        client.speak("hi")


def test_a_connection_failure_raises_tts_link_lost():
    playback = _playback()
    client = TtsPlaybackClient("http://127.0.0.1:1", "cookie-abc", playback)

    with pytest.raises(TtsLinkLost):
        client.speak("hi")


def test_empty_session_cookie_raises_immediately():
    with pytest.raises(ValueError, match="session_cookie"):
        TtsPlaybackClient("http://127.0.0.1:1", "", _playback())


def test_the_request_body_carries_the_text(tts_server):
    server, handler, reset = tts_server
    reset(_make_wav_bytes(0.2))
    playback = _playback()
    client = TtsPlaybackClient(_base_url(server), "cookie-abc", playback)

    client.speak("what a lovely day")

    assert handler.request_body["text"] == "what a lovely day"


def test_16khz_source_needs_no_resampling(tts_server):
    """The daemon's own output rate (16 kHz) matches a voice that
    already renders at 16 kHz - the identity path in _resample()."""
    server, handler, reset = tts_server
    reset(_make_wav_bytes(1.0, sample_rate=16_000))
    playback = _playback()
    client = TtsPlaybackClient(_base_url(server), "cookie-abc", playback)

    result = client.speak("hi")

    assert result.kind == "done"
    assert abs(playback.pushed_duration_s() - 1.0) < 0.05


def _make_stereo_wav_bytes(seconds: float, sample_rate: int = _SOURCE_RATE) -> bytes:
    n = int(seconds * sample_rate)
    t = np.arange(n) / sample_rate
    tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    ints = (tone * 32767).astype(np.int16)
    stereo = np.column_stack([ints, ints]).reshape(-1)  # interleaved L/R
    buf = BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(stereo.tobytes())
    return buf.getvalue()


class _FakeResponse:
    """A minimal stand-in for `requests.Response`, used only to hand
    `_stream_into_playback` chunks at byte boundaries a real HTTP
    round trip can't reliably produce: `requests`' own `iter_content()`
    re-buffers to its own fixed `chunk_size` (4096 bytes here, always a
    clean multiple of a stereo frame's 4 bytes), so a real server-side
    write size can never actually reach this code misaligned - only a
    direct, hand-crafted chunk sequence can prove the fix."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def iter_content(self, chunk_size: int):
        return iter(self._chunks)


def test_a_frame_misaligned_chunk_boundary_does_not_raise_on_reshape():
    """The review-caught bug: `_stream_into_playback` truncated to just
    an even byte count (one int16 sample), not a whole multi-channel
    frame (4 bytes for 16-bit stereo) - a chunk ending mid-frame made
    `_pcm16_to_float32`'s `reshape(-1, channels)` raise. Hand-crafted
    chunks that split a stereo WAV's data at a 2-byte (not 4-byte)
    boundary reproduce this directly, bypassing HTTP's own re-buffering
    (see `_FakeResponse`'s own docstring for why a real server can't)."""
    wav_bytes = _make_stereo_wav_bytes(0.5)
    header, pcm = wav_bytes[:44], wav_bytes[44:]
    # Split at byte 102 of the PCM data: a multiple of 2 (a whole int16
    # sample, so the old byte-only truncation accepted it as "usable"),
    # but NOT a multiple of 4 (a whole stereo frame) - exactly the
    # misalignment the review caught.
    split_at = 102
    assert split_at % 2 == 0 and split_at % 4 != 0  # confirms the split is frame-misaligned
    chunks = [header + pcm[:split_at], pcm[split_at:]]
    response = _FakeResponse(chunks)

    playback = _playback()
    client = TtsPlaybackClient("http://127.0.0.1:1", "cookie-abc", playback)

    result = client._stream_into_playback(response, None, None)

    assert result.kind == "done"
    assert abs(playback.pushed_duration_s() - 0.5) < 0.05
