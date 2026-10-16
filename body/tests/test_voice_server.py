"""VOICE-01: the speech process served over the shared voice contract."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np
import pytest
from websockets.sync.client import connect

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.speech.capture import AudioCapture
from maipai_body.speech.stt_stream import SttStreamClient
from maipai_body.speech.voice_server import (
    SttSession,
    SttWsServer,
    TtsHttpServer,
    parse_form_text,
    pcm16,
    wav_stream_header,
)
from tests.voice_fakes import LevelVad, ScriptedStt, ScriptedTts


def multipart(text: str | None, boundary: str = "XBOUNDARYX") -> tuple[str, bytes]:
    body = b""
    if text is not None:
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="text"\r\n\r\n{text}\r\n'
            f"--{boundary}--\r\n"
        ).encode()
    return f"multipart/form-data; boundary={boundary}", body


@pytest.fixture
def tts_server():
    server = TtsHttpServer(ScriptedTts())
    server.start()
    yield server
    server.stop()


def post_tts(server, text: str | None):
    content_type, body = multipart(text)
    request = urllib.request.Request(
        f"{server.url}/tts", data=body, headers={"Content-Type": content_type}, method="POST"
    )
    return urllib.request.urlopen(request, timeout=10)


def test_form_text_is_parsed_with_unicode_and_missing_field():
    assert parse_form_text(*multipart("It's 10:04, café.")) == "It's 10:04, café."
    assert parse_form_text(*multipart(None)) is None


def test_health_says_healthy(tts_server):
    with urllib.request.urlopen(f"{tts_server.url}/health", timeout=5) as resp:
        assert json.load(resp) == {"status": "healthy"}


def test_tts_streams_a_wav_whose_format_fields_are_right(tts_server):
    with post_tts(tts_server, "Hello there. How are you.") as resp:
        assert resp.headers["Content-Type"] == "audio/wav"
        data = resp.read()
    assert data[:4] == b"RIFF" and data[8:16] == b"WAVEfmt "
    channels, rate, bits = (
        int.from_bytes(data[22:24], "little"),
        int.from_bytes(data[24:28], "little"),
        int.from_bytes(data[34:36], "little"),
    )
    assert (channels, rate, bits) == (1, 22050, 16)
    assert len(data) - 44 == 2 * 22050  # two 0.5 s sentences of 16-bit mono


def test_tts_without_text_is_a_400_that_says_what_to_send(tts_server):
    with pytest.raises(urllib.error.HTTPError) as err:
        post_tts(tts_server, None)
    assert err.value.code == 400
    assert "text field" in err.value.read().decode()


def test_unknown_route_is_a_404(tts_server):
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(f"{tts_server.url}/nope", timeout=5)
    assert err.value.code == 404


def test_the_stream_header_parses_as_a_wav_for_a_buffered_reader():
    pcm = pcm16(np.full(100, 0.5, np.float32))
    header = wav_stream_header(16000)
    # A buffered consumer must at least read the format; the data size is a placeholder.
    with wave.open(io.BytesIO(header + pcm), "rb") as wav:
        assert (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) == (1, 16000, 2)


_HOME_BUN = Path.home() / ".bun" / "bin" / "bun"
BUN = shutil.which("bun") or (str(_HOME_BUN) if _HOME_BUN.is_file() else None)


@pytest.mark.skipif(BUN is None, reason="bun not installed")
def test_the_hub_typescript_client_talks_to_the_robot_voice(tts_server, tmp_path):
    spec = os.environ.get("MAIPAI_SPEC_DIR")
    if not spec or not (Path(spec) / "voice" / "ts" / "client.ts").is_file():
        pytest.skip("pinned spec source not found (set MAIPAI_SPEC_DIR)")
    script = tmp_path / "probe.ts"
    script.write_text(
        f"""
import {{ PocketTtsClient }} from "{spec}/voice/ts/client.ts";
const client = new PocketTtsClient("{tts_server.url}");
const healthy = await client.health();
const result = await client.synthesizeStream("Hello there. How are you.");
const bytes = new Uint8Array(await new Response(result.body).arrayBuffer());
console.log(JSON.stringify({{ healthy, type: result.contentType, size: bytes.length }}));
""",
        encoding="utf-8",
    )
    out = subprocess.run(
        [BUN or "bun", "run", str(script)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {
        "healthy": True,
        "type": "audio/wav",
        "size": 44 + 2 * 22050,
    }


# -- STT -----------------------------------------------------------------------


def write_wav(path: Path, parts: list[tuple[float, float]]) -> Path:
    """parts: (seconds, level) segments of 16 kHz mono."""
    samples = np.concatenate([np.full(round(16000 * s), lvl, np.float32) for s, lvl in parts])
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes((samples * 32767).astype("<i2").tobytes())
    return path


@pytest.fixture
def stt_server():
    stt = ScriptedStt("turn on the lights", "second one", "third one")

    def make(send):
        return SttSession(LevelVad(), stt, send)

    server = SttWsServer(make)
    server.start()
    server.stt = stt  # type: ignore[attr-defined]
    yield server
    server.stop()


def test_the_robot_stt_client_gets_a_final_from_the_robot_server(stt_server, tmp_path):
    wav = write_wav(tmp_path / "ask.wav", [(0.3, 0.0), (1.0, 0.3), (1.5, 0.0)])
    capture = AudioCapture(FakeReachyMiniClient(microphone_wav=wav))
    capture.start()
    client = SttStreamClient(stt_server.url, "cookie", wake_patience_s=6.0)
    result = client.run(capture)
    assert (result.kind, result.text) == ("final", "turn on the lights")
    heard = stt_server.stt.calls[0]
    assert 1.0 <= len(heard) / 16000 <= 2.2  # pre-roll and the speech, not the whole room


def test_silence_after_a_wake_gives_no_speech_when_the_client_ends(stt_server, tmp_path):
    wav = write_wav(tmp_path / "quiet.wav", [(1.0, 0.0)])
    capture = AudioCapture(FakeReachyMiniClient(microphone_wav=wav))
    capture.start()
    result = SttStreamClient(stt_server.url, "c", wake_patience_s=0.4).run(capture)
    assert result.kind == "no_speech" and stt_server.stt.calls == []


def test_wire_events_in_order_and_end_flushes_an_open_utterance(stt_server):
    speech = np.full(16000, 0.3, np.float32).astype("<f4").tobytes()
    with connect(stt_server.url.replace("http", "ws") + "/api/stt/stream") as ws:
        assert json.loads(ws.recv(timeout=5)) == {"t": "ready"}
        ws.send(speech)
        vad = json.loads(ws.recv(timeout=5))
        assert vad["t"] == "vad" and vad["speaking"] is True and vad["rms"] == pytest.approx(0.3)
        ws.send(json.dumps({"t": "end"}))
        assert json.loads(ws.recv(timeout=5)) == {"t": "vad", "speaking": False, "rms": 0.0}
        assert json.loads(ws.recv(timeout=5)) == {"t": "final", "v": "turn on the lights"}
        # The session is reusable for the next utterance on the same socket.
        ws.send(speech)
        ws.send(json.dumps({"t": "end"}))
        events = [json.loads(ws.recv(timeout=5)) for _ in range(3)]
        assert events[-1] == {"t": "final", "v": "second one"}


def test_end_with_nothing_heard_is_no_speech(stt_server):
    with connect(stt_server.url.replace("http", "ws") + "/api/stt/stream") as ws:
        ws.recv(timeout=5)
        ws.send(json.dumps({"t": "end"}))
        assert json.loads(ws.recv(timeout=5)) == {"t": "no_speech"}


def test_a_failing_engine_is_an_error_event_not_a_dropped_socket():
    sent: list[dict] = []

    class Boom(ScriptedStt):
        def transcribe(self, samples, sample_rate):
            raise RuntimeError("model gone")

    session = SttSession(LevelVad(), Boom(), sent.append)
    session.feed(np.full(16000, 0.3, np.float32))
    session.end()
    assert sent[-1]["t"] == "error" and "say it again" in sent[-1]["v"]


def test_the_wrong_path_is_a_404(stt_server):
    with pytest.raises(Exception) as err:
        connect(stt_server.url.replace("http", "ws") + "/other")
    assert "404" in str(err.value)
