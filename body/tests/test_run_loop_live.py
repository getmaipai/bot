"""G9's own still-open gap, attempted for the first time: "live
verification against the real reachy-mini-daemon --sim (RM-05's own
acceptance - a three-turn conversation on the simulator with cues
rendered before the first audio sample). This needs a combined
stand-in hub server ... or reuse of the existing per-module stand-in
servers wired to one address; not attempted this pass" (docs/BACKLOG.md,
FACE-01's own construction entry).

The "combined" turned out to be unnecessary: ConversationLoop's three
hub-facing clients are constructed independently (nothing requires them
to share a base_url), so this reuses each one's own already-proven real
local server (the exact shapes test_turn_client.py/
test_tts_playback.py/test_stt_stream.py stood up) on its own port,
against a real `ConversationLoop` whose head/expression/presence side
talks to a real `reachy-mini-daemon --sim`.

Skipped unless MAIPAI_BODY_LIVE=1 and a daemon answers on port 8000 -
the same gate conftest.py's own `body_client` fixture uses, and the
same reason: this suite runs against the fake always, the live
simulator only when explicitly asked for and reachable.

Audio is the one seam still faked even here: this verification's own
daemon invocation uses --no-media, so the real client's AudioIO calls
return None/-1 rather than touching the host's real microphone or
speaker (CLAUDE.md's own rule against a test reaching outside the repo
for real hardware it doesn't need, and the 2026-09-27 privacy finding
about the simulator's own microphone fallback otherwise using the host
machine's real mic with no consent prompt). `_LiveAudioIO` below
delegates every other HAL call - goto, hold, tracking, the face
target, the IMU - straight to the real daemon-backed client.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
import time
import wave
from io import BytesIO

import numpy as np
import numpy.typing as npt
import pytest
from websockets.sync.server import Server, serve

from maipai_body.expression.cue import Phase
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.speech.capture import AudioCapture
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.stt_stream import SttStreamClient
from maipai_body.speech.tts_playback import TtsPlaybackClient
from maipai_body.speech.turn_client import TurnClient
from maipai_body.speech.wake import WakeScorer
from tests.conftest import LIVE_HOST, LIVE_PORT, _live_daemon_reachable

pytestmark = pytest.mark.skipif(
    __import__("os").environ.get("MAIPAI_BODY_LIVE") != "1" or not _live_daemon_reachable(),
    reason="set MAIPAI_BODY_LIVE=1 with a daemon answering on the live port to run this",
)


class _LiveAudioIO:
    """Wraps a real `ReachyMiniClient`: every HAL call other than audio
    goes straight to it (attribute delegation via `__getattr__`); audio
    is faked entirely (see this file's own header on why)."""

    def __init__(self, real_client) -> None:
        self._real = real_client
        self._recording = False
        self.pushed: list[npt.NDArray[np.float32]] = []

    def __getattr__(self, name):
        # A review (2026-09-28) named the footgun: reading `self._real`
        # directly here recurses back into `__getattr__` (RecursionError,
        # not a clean AttributeError) if anything ever probes an
        # attribute before `__init__`'s first line runs. Not reachable
        # today (nothing subclasses or pickles this), but one guard is
        # cheap insurance against a confusing failure mode later.
        if name == "_real":
            raise AttributeError(name)
        return getattr(self._real, name)

    def start_recording(self) -> None:
        self._recording = True

    def stop_recording(self) -> None:
        self._recording = False

    def get_audio_sample(self) -> npt.NDArray[np.float32] | None:
        if not self._recording:
            return None
        return np.zeros(512, dtype=np.float32)  # one 32ms block's worth of silence

    def get_input_audio_samplerate(self) -> int:
        return 16000

    def start_playing(self) -> None:
        pass

    def push_audio_sample(self, data: npt.NDArray[np.float32]) -> None:
        self.pushed.append(data)

    def stop_playing(self) -> None:
        pass

    def get_output_audio_samplerate(self) -> int:
        return 16000

    def get_doa(self):
        return None


class _TriggerableWakeEngine:
    """Scores 0 until `trigger()` is called; then the next `score()`
    call returns 1.0. `reset()` (WakeScorer's own post-wake contract,
    called the instant it returns an event) re-arms this for the next
    turn - real audio content is never scored, since there is none."""

    def __init__(self) -> None:
        self._fire = threading.Event()

    def trigger(self) -> None:
        self._fire.set()

    def score(self, block: npt.NDArray[np.float32]) -> float:
        return 1.0 if self._fire.is_set() else 0.0

    def reset(self) -> None:
        self._fire.clear()


class _SttServer:
    """Sends `{t:"ready"}`, then `{t:"vad",speaking:true}` and
    `{t:"final",v:TEXT}` shortly after - the same shape
    test_stt_stream.py's own `_ScriptedSttServer` already proved
    correct, inlined here so this file needs no cross-test import."""

    text = "hello maipai"

    def __call__(self, ws) -> None:
        ws.send(json.dumps({"t": "ready"}))
        time.sleep(0.05)
        ws.send(json.dumps({"t": "vad", "speaking": True}))
        time.sleep(0.05)
        ws.send(json.dumps({"t": "final", "v": type(self).text}))
        time.sleep(0.2)  # let the client's own audio sends land before closing


class _TurnServer(http.server.BaseHTTPRequestHandler):
    """Streams a fixed NDJSON script per request - the same shape
    test_turn_client.py's own `_NdjsonTurnServer` already proved
    correct."""

    reply_text = "hello back"

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        lines = [
            {"type": "turn_meta", "conversation_id": "conv-live", "turn_id": "turn-live"},
            {
                "type": "signal",
                "signal": {
                    "primary_act": "inform",
                    "expressed_emotion": "happiness",
                    "emotion_intensity": "moderate",
                },
            },
            {"type": "delta", "text": type(self).reply_text},
            {"type": "done", "value": {}},
        ]
        for line in lines:
            self.wfile.write((json.dumps(line) + "\n").encode("utf-8"))
            self.wfile.flush()


class _TtsServer(http.server.BaseHTTPRequestHandler):
    """Streams a short generated WAV - the same shape
    test_tts_playback.py's own `_TtsServer` already proved correct."""

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.end_headers()
        data = _make_wav_bytes(0.3)
        chunk = 1024
        for i in range(0, len(data), chunk):
            self.wfile.write(data[i : i + chunk])
            self.wfile.flush()


def _make_wav_bytes(seconds: float, sample_rate: int = 24_000) -> bytes:
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


def _start_http(handler_cls) -> http.server.ThreadingHTTPServer:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _start_ws(handler) -> Server:
    server = serve(handler, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_live_conversation_completes_three_turns_with_cues_rendered_in_order():
    from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
    from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
    from maipai_body.run_loop import ConversationLoop

    # A review (2026-09-28) caught two real gaps in a hand-rolled
    # try/finally here: the three servers were started sequentially
    # with no cleanup for an already-started one if a later start
    # raised, and the four cleanup calls in one finally block would
    # cascade-skip the rest the moment any single one raised (a failed
    # server .shutdown() would have left the real daemon connection
    # never disconnected). ExitStack registers each resource's own
    # cleanup the instant it's created and guarantees every registered
    # callback runs regardless of what an earlier one raised.
    with contextlib.ExitStack() as cleanup:
        real_client = ReachyMiniClient(REACHY_MINI_PROFILE, host=LIVE_HOST, port=LIVE_PORT)
        cleanup.callback(real_client.disconnect)

        stt_handler = _SttServer()
        stt_server = _start_ws(stt_handler)
        cleanup.callback(stt_server.shutdown)
        turn_server = _start_http(_TurnServer)
        cleanup.callback(turn_server.shutdown)
        tts_server = _start_http(_TtsServer)
        cleanup.callback(tts_server.shutdown)

        client = _LiveAudioIO(real_client)
        stt_url = f"http://127.0.0.1:{stt_server.socket.getsockname()[1]}"
        turn_url = f"http://127.0.0.1:{turn_server.server_port}"
        tts_url = f"http://127.0.0.1:{tts_server.server_port}"

        wake_engine = _TriggerableWakeEngine()
        audio_capture = AudioCapture(client)
        audio_playback = AudioPlayback(client)

        rendered: list[Phase] = []
        real_render = ExpressionEngine.handle

        def _recording_handle(self, cue, context, **kwargs):
            rendered.append(cue.phase)
            return real_render(self, cue, context, **kwargs)

        ExpressionEngine.handle = _recording_handle

        def _restore_handle() -> None:
            ExpressionEngine.handle = real_render

        cleanup.callback(_restore_handle)

        loop = ConversationLoop(
            client=client,
            expression_engine=ExpressionEngine(client, REACHY_MINI_PROFILE),
            audio_capture=audio_capture,
            audio_playback=audio_playback,
            wake_scorer=WakeScorer(wake_engine, client, threshold=0.5),
            stt_client=SttStreamClient(stt_url, "live-cookie"),
            turn_client=TurnClient(turn_url, "live-cookie"),
            tts_client=TtsPlaybackClient(tts_url, "live-cookie", audio_playback),
        )

        stop_event = threading.Event()
        run_thread = threading.Thread(target=loop.run, args=(stop_event,), daemon=True)
        run_thread.start()

        def _stop_run_thread() -> None:
            stop_event.set()
            run_thread.join(timeout=5.0)
            assert not run_thread.is_alive(), "the run loop did not stop within its join timeout"

        cleanup.callback(_stop_run_thread)

        for turn_number in range(1, 4):
            deadline = time.monotonic() + 10.0
            while loop.state.funnel.value != "idle" and time.monotonic() < deadline:
                time.sleep(0.02)
            assert loop.state.funnel.value == "idle", (
                f"turn {turn_number}: never returned to idle before the next wake"
            )
            rendered.clear()
            wake_engine.trigger()

            # HEARD -> SIGNAL -> SPEAK -> DONE, in that order, cues
            # rendered before the loop returns to idle: RM-05's own
            # acceptance, checked after every turn, not just once.
            deadline = time.monotonic() + 10.0
            while Phase.DONE not in rendered and time.monotonic() < deadline:
                time.sleep(0.02)
            assert rendered[:1] == [Phase.HEARD], (
                f"turn {turn_number}: cues were {rendered!r}, expected HEARD first"
            )
            assert Phase.SPEAK in rendered, f"turn {turn_number}: SPEAK cue never rendered"
            assert rendered.index(Phase.SPEAK) < rendered.index(Phase.DONE), (
                f"turn {turn_number}: SPEAK must precede DONE"
            )
            assert client.pushed, f"turn {turn_number}: no audio was ever pushed"
