"""M-R5's sim-first rows, deterministic half: Wi-Fi loss mid-turn and mid-sentence.

Design record section 7: loss of the hub mid-turn is ``cancel`` with
reason ``link_lost``; M-R5 adds the pose settled and the one line spoken
on reconnect if a turn was lost (section 4: once per outage). Driven
through the real ``ConversationLoop`` and a real ``ExpressionEngine``
rendering onto ``FakeReachyMiniClient``, so "cancel raised" and "pose
settled" are read off what actually reached the seam.
"""

from __future__ import annotations

from collections.abc import Iterator

from maipai_body.expression.cue import Cue, Phase
from maipai_body.run_loop import FunnelState
from maipai_body.speech.stt_stream import SttStreamError, SttStreamResult
from maipai_body.speech.tts_playback import TtsLinkLost
from maipai_body.speech.turn_client import TurnEvent, TurnLinkLost
from maipai_body.speech.wake import WakeEvent
from tests.test_run_loop import (
    _make_loop,
    _start,
    _stop,
    _wait_for,
    _wait_for_idle_after_turn,
)

_SIGNAL = TurnEvent(
    cue=Cue(phase=Phase.SIGNAL, cue_seq=1, primary_act="inform", react_allowed=True),
    conversation_id="conv-1",
    turn_id="turn-1",
)


def _done(reply: str) -> TurnEvent:
    return TurnEvent(
        cue=Cue(phase=Phase.DONE, cue_seq=2),
        reply_text=reply,
        conversation_id="conv-1",
        turn_id="turn-1",
    )


class _SequencedTurnClient:
    """One script per call. A script is a list of events; an exception in it
    is raised at that point in the stream, as a socket dying mid-response does."""

    def __init__(self, scripts: list[list]) -> None:
        self._scripts = list(scripts)
        self.stream_calls: list[str] = []
        self.cancel_calls: list[str] = []

    def stream(self, text: str, **_kwargs) -> Iterator[TurnEvent]:
        self.stream_calls.append(text)
        script = self._scripts.pop(0)

        def _gen():
            for item in script:
                if isinstance(item, Exception):
                    raise item
                yield item

        return _gen()

    def cancel(self, turn_id: str) -> bool:
        self.cancel_calls.append(turn_id)
        return True


class _SequencedTts:
    """One behavior per call: "ok", "drop_after_first_chunk" or "drop_before_audio"."""

    def __init__(self, behaviors: list[str]) -> None:
        self._behaviors = list(behaviors)
        self.speak_calls: list[str] = []

    def speak(self, text: str, *, on_first_chunk=None, stop_event=None):
        self.speak_calls.append(text)
        behavior = self._behaviors.pop(0) if self._behaviors else "ok"
        if behavior == "drop_before_audio":
            raise TtsLinkLost("connection reset before any audio")
        if on_first_chunk is not None:
            on_first_chunk()
        if behavior == "drop_after_first_chunk":
            raise TtsLinkLost("connection reset mid-sentence")


def _loop_with(turn_scripts: list[list], tts_behaviors: list[str], *, turns: int, stt=None):
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)] * turns,
        stt_result=stt or SttStreamResult(kind="final", text="hello"),
    )
    parts["turn"] = _SequencedTurnClient(turn_scripts)
    parts["tts"] = _SequencedTts(tts_behaviors)
    loop._turn = parts["turn"]
    loop._tts = parts["tts"]
    return loop, parts


def _phases(parts) -> list[Phase]:
    return [phase for phase, _muted in parts["engine"].handled]


def _wait_for_turns(loop, count: int) -> None:
    _wait_for(
        lambda: (
            sum(1 for t in loop.state.trace if t.state == FunnelState.LISTENING) >= count
            and loop.state.trace[-1].state == FunnelState.IDLE
        )
    )


def _last_command_kind(parts) -> str:
    return parts["client"].sent_commands[-1].kind


def test_the_link_dropping_mid_turn_raises_one_cancel_and_settles_the_pose():
    loop, parts = _loop_with([[_SIGNAL, TurnLinkLost("wifi gone")]], [], turns=1)
    stop_event, thread = _start(loop)
    try:
        _wait_for_idle_after_turn(loop)
        assert _phases(parts) == [Phase.HEARD, Phase.SIGNAL, Phase.CANCEL]
        assert _last_command_kind(parts) == "hold"  # stop holds the pose: settled
        assert parts["tts"].speak_calls == []
    finally:
        _stop(stop_event, thread)


def test_the_link_dropping_mid_sentence_raises_one_cancel_not_a_done():
    loop, parts = _loop_with([[_done("it is sunny")]], ["drop_after_first_chunk"], turns=1)
    stop_event, thread = _start(loop)
    try:
        _wait_for_idle_after_turn(loop)
        assert _phases(parts) == [Phase.HEARD, Phase.SPEAK, Phase.CANCEL]
        assert _last_command_kind(parts) == "hold"
        assert parts["playback"].stop_calls >= 1
    finally:
        _stop(stop_event, thread)


def test_the_link_dropping_before_any_audio_raises_one_cancel():
    loop, parts = _loop_with([[_done("it is sunny")]], ["drop_before_audio"], turns=1)
    stop_event, thread = _start(loop)
    try:
        _wait_for_idle_after_turn(loop)
        assert _phases(parts) == [Phase.HEARD, Phase.CANCEL]
    finally:
        _stop(stop_event, thread)


def test_the_link_dropping_while_listening_settles_the_pose_the_listen_cue_moved():
    loop, parts = _loop_with([], [], turns=1)
    parts["stt"].run = lambda capture: (_ for _ in ()).throw(SttStreamError("wifi gone"))
    stop_event, thread = _start(loop)
    try:
        _wait_for_idle_after_turn(loop)
        assert _phases(parts) == [Phase.HEARD, Phase.CANCEL]
        assert _last_command_kind(parts) == "hold"
    finally:
        _stop(stop_event, thread)


def test_a_lost_turn_is_announced_once_on_the_next_reply_that_reaches_the_hub():
    from maipai_body.run_loop import LINK_RESTORED_LINE

    loop, parts = _loop_with(
        [[_SIGNAL, TurnLinkLost("wifi gone")], [_done("it is sunny")], [_done("still sunny")]],
        [],
        turns=3,
    )
    stop_event, thread = _start(loop)
    try:
        _wait_for_turns(loop, 3)
        spoken = parts["tts"].speak_calls
        assert len(spoken) == 2
        assert spoken[0].startswith(LINK_RESTORED_LINE)
        assert spoken[0].endswith("it is sunny")
        assert spoken[1] == "still sunny"  # once, never repeated
    finally:
        _stop(stop_event, thread)


def test_several_lost_turns_in_one_outage_are_announced_once():
    from maipai_body.run_loop import LINK_RESTORED_LINE

    loop, parts = _loop_with(
        [[TurnLinkLost("down")], [TurnLinkLost("still down")], [_done("back")]],
        [],
        turns=3,
    )
    stop_event, thread = _start(loop)
    try:
        _wait_for_turns(loop, 3)
        spoken = parts["tts"].speak_calls
        assert len(spoken) == 1
        assert spoken[0].count(LINK_RESTORED_LINE) == 1
    finally:
        _stop(stop_event, thread)


def test_nothing_is_announced_when_no_turn_was_lost():
    loop, parts = _loop_with([[_done("it is sunny")]], [], turns=1)
    stop_event, thread = _start(loop)
    try:
        _wait_for_turns(loop, 1)
        assert parts["tts"].speak_calls == ["it is sunny"]
    finally:
        _stop(stop_event, thread)


def test_a_cancel_the_hub_itself_sent_is_not_a_lost_link():
    cancel = TurnEvent(cue=Cue(phase=Phase.CANCEL, cue_seq=1), turn_id="turn-1")
    loop, parts = _loop_with([[cancel], [_done("it is sunny")]], [], turns=2)
    stop_event, thread = _start(loop)
    try:
        _wait_for_turns(loop, 2)
        assert parts["tts"].speak_calls == ["it is sunny"]
    finally:
        _stop(stop_event, thread)
