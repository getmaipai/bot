"""G9's own acceptance: the funnel state machine driving audio, cues,
tracking and barge-in, exercised against scripted stand-ins for every
network-facing dependency (wake scoring, STT, the turn stream, TTS
playback - each already has its own real-server-backed suite) and a
real ``ExpressionEngine`` rendering onto ``FakeReachyMiniClient``, so
the cue-to-primitive path is genuinely exercised, not just assumed.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.cue import Cue, Phase
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.hal.seam import FaceTrackTarget
from maipai_body.run_loop import ConversationLoop, FunnelState
from maipai_body.speech.stt_stream import SttStreamResult
from maipai_body.speech.tts_playback import TtsLinkLost
from maipai_body.speech.turn_client import TurnEvent, TurnLinkLost
from maipai_body.speech.wake import WakeEvent


class _RecordingExpressionEngine:
    """Wraps a real :class:`ExpressionEngine` (so rendering onto the fake
    body client is genuinely exercised) while recording the phase and
    mute state of every call, in order, for assertions."""

    def __init__(self, client, profile) -> None:
        self._engine = ExpressionEngine(client, profile)
        self.handled: list[tuple[Phase, bool]] = []
        self.muted_calls: list[bool] = []

    def handle(self, cue: Cue, context, **kwargs):
        self.handled.append((cue.phase, context.muted))
        return self._engine.handle(cue, context, **kwargs)

    def set_muted(self, muted: bool, arbitration):
        self.muted_calls.append(muted)
        return self._engine.set_muted(muted, arbitration)


class _FakeAudioCapture:
    """One dummy block per call, always - content is irrelevant since
    the wake scorer below is scripted, not a real model."""

    def __init__(self) -> None:
        import numpy as np

        self._block = np.zeros(512, dtype="float32")
        self.started = False
        self.stopped = False
        self.poll_count = 0

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def poll_blocks(self):
        self.poll_count += 1
        return [self._block]


class _FakeAudioPlayback:
    def __init__(self) -> None:
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


class _ScriptedWakeScorer:
    """Returns the next scripted entry (a :class:`WakeEvent` or ``None``)
    per call, in order; ``None`` once the script runs out, matching a
    real scorer's steady-state "nothing yet"."""

    def __init__(self, script) -> None:
        self._script = list(script)
        self.poll_count = 0

    def poll(self, block) -> WakeEvent | None:
        self.poll_count += 1
        if self._script:
            return self._script.pop(0)
        return None


class _ScriptedSttStreamClient:
    def __init__(self, result: SttStreamResult) -> None:
        self._result = result
        self.call_count = 0

    def run(self, capture) -> SttStreamResult:
        self.call_count += 1
        return self._result


class _ScriptedTurnClient:
    def __init__(self, events: list[TurnEvent]) -> None:
        self._events = events
        self.stream_calls: list[str] = []
        self.cancel_calls: list[str] = []
        self.cancel_return = True

    def stream(self, text: str) -> Iterator[TurnEvent]:
        self.stream_calls.append(text)
        return iter(self._events)

    def cancel(self, turn_id: str) -> bool:
        self.cancel_calls.append(turn_id)
        return self.cancel_return


class _RaisingTurnClient:
    """A turn stream that fails mid-connection - the `TurnLinkLost`/
    `requests.RequestException` path `_run_turn` must also handle."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.cancel_calls: list[str] = []

    def stream(self, text: str) -> Iterator[TurnEvent]:
        def _gen():
            raise self._exc
            yield  # pragma: no cover - unreachable, makes this a generator

        return _gen()

    def cancel(self, turn_id: str) -> bool:
        self.cancel_calls.append(turn_id)
        return True


class _ScriptedTtsPlaybackClient:
    """``behavior="quick"`` returns the instant `on_first_chunk` fires
    (the ordinary happy path). ``behavior="hang_until_stop"`` blocks
    until its own `stop_event` is set - the barge-in test's own way of
    holding `speaking` open long enough for a second wake to land.
    ``behavior="hang_until_stop_plus_grace"`` additionally stays alive
    for a further beat after `stop_event` fires, simulating a worker
    that is slow to actually exit - the double-barge-in regression
    test's own way of proving the outer loop stops polling wake the
    instant `barge_in` is set, not just once the thread has died.
    ``behavior="error"`` raises, matching a dropped TTS connection."""

    def __init__(self, behavior: str = "quick") -> None:
        self.behavior = behavior
        self.speak_calls: list[str] = []

    def speak(self, text: str, *, on_first_chunk=None, stop_event: threading.Event | None = None):
        self.speak_calls.append(text)
        if self.behavior == "error":
            raise TtsLinkLost("tts connection failed")
        if on_first_chunk is not None:
            on_first_chunk()
        if self.behavior in ("hang_until_stop", "hang_until_stop_plus_grace"):
            while stop_event is not None and not stop_event.is_set():
                time.sleep(0.005)
        if self.behavior == "hang_until_stop_plus_grace":
            time.sleep(0.15)
        return None


def _make_loop(
    *,
    wake_events=(),
    stt_result: SttStreamResult | None = None,
    turn_events: list[TurnEvent] | None = None,
    turn_raises: Exception | None = None,
    tts_behavior: str = "quick",
    presence_interval_s: float = 5.0,
):
    client = FakeReachyMiniClient(REACHY_MINI_PROFILE)
    engine = _RecordingExpressionEngine(client, REACHY_MINI_PROFILE)
    capture = _FakeAudioCapture()
    playback = _FakeAudioPlayback()
    wake = _ScriptedWakeScorer(wake_events)
    stt = _ScriptedSttStreamClient(stt_result or SttStreamResult(kind="no_speech"))
    turn = (
        _RaisingTurnClient(turn_raises)
        if turn_raises is not None
        else _ScriptedTurnClient(turn_events or [])
    )
    tts = _ScriptedTtsPlaybackClient(tts_behavior)
    loop = ConversationLoop(
        client=client,
        expression_engine=engine,
        audio_capture=capture,
        audio_playback=playback,
        wake_scorer=wake,
        stt_client=stt,
        turn_client=turn,
        tts_client=tts,
        presence_interval_s=presence_interval_s,
    )
    parts = {
        "client": client,
        "engine": engine,
        "capture": capture,
        "playback": playback,
        "wake": wake,
        "stt": stt,
        "turn": turn,
        "tts": tts,
    }
    return loop, parts


def _start(loop: ConversationLoop) -> tuple[threading.Event, threading.Thread]:
    stop_event = threading.Event()
    thread = threading.Thread(target=loop.run, args=(stop_event,), daemon=True)
    thread.start()
    return stop_event, thread


def _stop(stop_event: threading.Event, thread: threading.Thread) -> None:
    stop_event.set()
    thread.join(timeout=3.0)
    assert not thread.is_alive()


def _wait_for(predicate, *, timeout: float = 3.0, interval: float = 0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("timed out waiting for condition")


def _wait_for_idle_after_turn(loop: ConversationLoop, *, timeout: float = 3.0) -> None:
    _wait_for(
        lambda: bool(loop.state.trace) and loop.state.trace[-1].state == FunnelState.IDLE,
        timeout=timeout,
    )


def test_happy_path_renders_cues_in_order_and_returns_to_idle():
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="what's the weather"),
        turn_events=[
            TurnEvent(
                cue=Cue(
                    phase=Phase.SIGNAL,
                    cue_seq=1,
                    primary_act="inform",
                    expressed_emotion="happiness",
                    emotion_intensity="moderate",
                ),
                conversation_id="conv-1",
                turn_id="turn-1",
            ),
            TurnEvent(
                cue=Cue(phase=Phase.DONE, cue_seq=2),
                reply_text="it's sunny",
                conversation_id="conv-1",
                turn_id="turn-1",
            ),
        ],
        tts_behavior="quick",
    )

    stop_event, thread = _start(loop)
    try:
        _wait_for_idle_after_turn(loop)
        phases = [phase for phase, _muted in parts["engine"].handled]
        assert phases == [Phase.HEARD, Phase.SIGNAL, Phase.SPEAK, Phase.DONE]
        assert parts["tts"].speak_calls == ["it's sunny"]
        assert parts["turn"].stream_calls == ["what's the weather"]
        assert [t.state for t in loop.state.trace] == [
            FunnelState.LISTENING,
            FunnelState.THINKING,
            FunnelState.SPEAKING,
            FunnelState.IDLE,
        ]
    finally:
        _stop(stop_event, thread)


def test_no_speech_returns_to_idle_without_a_turn_call():
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="no_speech"),
    )

    stop_event, thread = _start(loop)
    try:
        _wait_for_idle_after_turn(loop)
        phases = [phase for phase, _muted in parts["engine"].handled]
        assert phases == [Phase.HEARD]
        assert parts["turn"].stream_calls == []
        assert parts["tts"].speak_calls == []
    finally:
        _stop(stop_event, thread)


def test_a_cancel_cue_from_the_turn_stream_skips_speech():
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="never mind"),
        turn_events=[
            TurnEvent(
                cue=Cue(phase=Phase.CANCEL, cue_seq=1),
                conversation_id="conv-1",
                turn_id="turn-1",
            ),
        ],
    )

    stop_event, thread = _start(loop)
    try:
        _wait_for_idle_after_turn(loop)
        phases = [phase for phase, _muted in parts["engine"].handled]
        assert phases == [Phase.HEARD, Phase.CANCEL]
        assert parts["tts"].speak_calls == []
    finally:
        _stop(stop_event, thread)


def test_a_dropped_turn_stream_connection_renders_cancel_and_returns_idle():
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="hello"),
        turn_raises=TurnLinkLost("connection dropped"),
    )

    stop_event, thread = _start(loop)
    try:
        _wait_for_idle_after_turn(loop)
        phases = [phase for phase, _muted in parts["engine"].handled]
        assert phases == [Phase.HEARD, Phase.CANCEL]
        assert parts["tts"].speak_calls == []
    finally:
        _stop(stop_event, thread)


def test_a_second_wake_during_speaking_barges_in_and_cancels_the_turn():
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9), None, None, WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="tell me a story"),
        turn_events=[
            TurnEvent(
                cue=Cue(phase=Phase.DONE, cue_seq=1),
                reply_text="once upon a time",
                conversation_id="conv-1",
                turn_id="turn-1",
            ),
        ],
        tts_behavior="hang_until_stop",
    )

    stop_event, thread = _start(loop)
    try:
        _wait_for(lambda: loop.state.funnel == FunnelState.SPEAKING)
        _wait_for_idle_after_turn(loop)
        phases = [phase for phase, _muted in parts["engine"].handled]
        assert phases == [Phase.HEARD, Phase.SPEAK, Phase.CANCEL]
        assert Phase.DONE not in phases  # barge-in preempts the DONE render
        assert parts["turn"].cancel_calls == ["turn-1"]
        assert parts["playback"].stop_calls == 1
    finally:
        _stop(stop_event, thread)


def test_a_second_wake_block_after_barge_in_does_not_double_cancel():
    """The review-caught bug (2026-09-28): the barge-in loop used to
    keep polling wake for as long as `speak_thread.is_alive()`, so a
    worker that was slow to actually exit after `barge_in` was set
    could have a further wake block scored - re-cancelling the turn and
    re-rendering CANCEL. Calls `_speak()` directly (not through `run()`)
    so a second scripted wake event left over after the fix correctly
    stops consuming the script isn't later picked up by `_poll_wake`'s
    own next cycle as a legitimate new wake - that would just be this
    test's own script leaking into an unrelated turn, not evidence
    about the barge-in loop itself."""
    loop, parts = _make_loop(
        # Two quiet ticks, then the barge-in hit, then a further real
        # event sitting exactly where the old code's extra grace-period
        # tick would have consumed it as a second "hit."
        wake_events=[None, None, WakeEvent(score=0.9), WakeEvent(score=0.9)],
        tts_behavior="hang_until_stop_plus_grace",
    )

    outer_stop_event = threading.Event()
    speak_thread = threading.Thread(
        target=loop._speak, args=("once upon a time", "turn-1", outer_stop_event), daemon=True
    )
    speak_thread.start()
    try:
        speak_thread.join(timeout=3.0)
        assert not speak_thread.is_alive()
        phases = [phase for phase, _muted in parts["engine"].handled]
        assert phases.count(Phase.CANCEL) == 1
        assert parts["turn"].cancel_calls == ["turn-1"]
        assert parts["wake"].poll_count == 3  # 2 quiet ticks, then the one real barge-in hit
    finally:
        outer_stop_event.set()
        speak_thread.join(timeout=3.0)


def test_presence_enables_tracking_when_face_present_and_not_speaking():
    loop, parts = _make_loop(presence_interval_s=0.02)
    client = parts["client"]
    client.face_target = FaceTrackTarget(detected=True)

    stop_event = threading.Event()
    thread = threading.Thread(target=loop._presence_loop, args=(stop_event,), daemon=True)
    thread.start()
    try:
        _wait_for(lambda: client.tracking_enabled is True)

        client.face_target = FaceTrackTarget(detected=False)
        _wait_for(lambda: client.tracking_enabled is False)
    finally:
        stop_event.set()
        thread.join(timeout=2.0)


def test_presence_never_enables_tracking_while_already_speaking():
    loop, parts = _make_loop(presence_interval_s=0.02)
    client = parts["client"]
    client.face_target = FaceTrackTarget(detected=True)
    loop._enter(FunnelState.SPEAKING)

    stop_event = threading.Event()
    thread = threading.Thread(target=loop._presence_loop, args=(stop_event,), daemon=True)
    thread.start()
    try:
        time.sleep(0.15)  # several presence ticks at this interval
        assert client.tracking_enabled is False
    finally:
        stop_event.set()
        thread.join(timeout=2.0)


def test_set_muted_is_edge_triggered_and_updates_state():
    loop, parts = _make_loop()
    engine = parts["engine"]

    loop.set_muted(True)
    assert loop.state.muted is True
    assert engine.muted_calls == [True]

    loop.set_muted(True)  # no-op: already muted
    assert engine.muted_calls == [True]

    loop.set_muted(False)
    assert loop.state.muted is False
    assert engine.muted_calls == [True, False]


def test_poll_wake_drains_capture_but_never_scores_while_muted():
    loop, parts = _make_loop(wake_events=[WakeEvent(score=0.9)])
    capture = parts["capture"]
    wake = parts["wake"]
    loop.set_muted(True)

    stop_event = threading.Event()
    result: dict[str, object] = {}

    def _poll():
        result["event"] = loop._poll_wake(stop_event)

    thread = threading.Thread(target=_poll, daemon=True)
    thread.start()
    try:
        time.sleep(0.1)
        assert wake.poll_count == 0
        assert capture.poll_count > 0
    finally:
        stop_event.set()
        thread.join(timeout=2.0)
    assert result["event"] is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
