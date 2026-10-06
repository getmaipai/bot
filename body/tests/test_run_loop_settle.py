"""BODY-05 on the existing G9 funnel: the 0.5 s settle gate is enforced and
the settled state is exposed to readers (the link, the director, tests).

One funnel, never two: the raw state the loop acts on (barge-in, tracking,
the line rules) is untouched and still recorded in ``RunLoopState.trace``;
``RunLoopState.shown`` and ``shown_trace`` are what readers are given.
"""

from __future__ import annotations

import inspect

from maipai_body.expression.cue import Cue, Phase
from maipai_body.run_loop import SETTLE_GATE_S, ConversationLoop, FunnelState
from maipai_body.speech.stt_stream import SttStreamResult
from maipai_body.speech.turn_client import TurnEvent
from maipai_body.speech.wake import WakeEvent
from tests.test_run_loop import _make_loop, _start, _stop, _wait_for

GATE_S = 0.15


def _quick_turn_loop(**kwargs):
    return _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="hello"),
        turn_events=[
            TurnEvent(
                cue=Cue(phase=Phase.DONE, cue_seq=1),
                reply_text="hi",
                conversation_id="c",
                turn_id="t",
            ),
        ],
        settle_gate_s=GATE_S,
        **kwargs,
    )


def test_the_gate_is_half_a_second_by_default():
    assert SETTLE_GATE_S == 0.5
    default = inspect.signature(ConversationLoop.__init__).parameters["settle_gate_s"].default
    assert default == SETTLE_GATE_S


def test_a_fast_turn_never_shows_a_state_shorter_than_the_gate():
    loop, _ = _quick_turn_loop()
    stop_event, thread = _start(loop)
    try:
        _wait_for(
            lambda: (
                loop.state.shown_trace[-1:] and loop.state.shown_trace[-1].state == FunnelState.IDLE
            )
        )
        raw = [t.state for t in loop.state.trace]
        assert raw == [
            FunnelState.LISTENING,
            FunnelState.THINKING,
            FunnelState.SPEAKING,
            FunnelState.IDLE,
        ], "the raw trace keeps the real transitions"
        shown = loop.state.shown_trace
        assert [t.state for t in shown] == [FunnelState.LISTENING, FunnelState.IDLE]
        assert shown[1].at_monotonic - shown[0].at_monotonic >= GATE_S - 0.005
    finally:
        _stop(stop_event, thread)


def test_readers_see_the_held_state_while_the_loop_already_acts_on_the_raw_one():
    loop, _ = _quick_turn_loop()
    stop_event, thread = _start(loop)
    try:
        _wait_for(lambda: len(loop.state.trace) == 4)
        state = loop.state
        assert state.funnel == FunnelState.IDLE
        assert state.shown == FunnelState.LISTENING
        assert loop.snapshot()["activity"] == "listening"
        _wait_for(lambda: loop.state.shown == FunnelState.IDLE)
        assert loop.snapshot()["activity"] == "idle"
    finally:
        _stop(stop_event, thread)


def test_subscribers_are_told_only_the_shown_changes():
    loop, _ = _quick_turn_loop()
    heard: list[FunnelState] = []
    loop.subscribe_funnel(heard.append)
    stop_event, thread = _start(loop)
    try:
        _wait_for(lambda: heard[-1:] == [FunnelState.IDLE])
        assert heard == [FunnelState.LISTENING, FunnelState.IDLE]
    finally:
        _stop(stop_event, thread)
