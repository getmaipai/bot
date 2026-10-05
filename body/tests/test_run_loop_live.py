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
machine's real mic with no consent prompt). `NullAudioIO` (`maipai_body/measure/loop_bench.py`)
delegates every other HAL call - goto, hold, tracking, the face
target, the IMU - straight to the real daemon-backed client.
"""

from __future__ import annotations

import contextlib
import threading
import time

import pytest

from maipai_body.expression.cue import Phase
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.measure.loop_bench import NullAudioIO, TriggerableWakeEngine
from maipai_body.measure.stand_in_hub import StandInHub
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

        hub = cleanup.enter_context(StandInHub(reply_text="hello back", stt_text="hello maipai"))

        client = NullAudioIO(real_client)

        wake_engine = TriggerableWakeEngine()
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
            stt_client=SttStreamClient(hub.stt_url, "live-cookie"),
            turn_client=TurnClient(hub.http_url, "live-cookie"),
            tts_client=TtsPlaybackClient(hub.http_url, "live-cookie", audio_playback),
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
