"""LINK-STATE-01: the funnel and run loop with the ladder, on a fake body and an injected clock."""

from __future__ import annotations

import datetime
import threading
import time
from unittest.mock import Mock

import requests

from maipai_body.hal.seam import FaceTrackTarget
from maipai_body.link.commands import CommandRouter, LocalTimers
from maipai_body.link.offline import OfflineRungs
from maipai_body.link.replay import ReplayGate
from maipai_body.link.rung0 import Rung0Cues, Rung0Settings
from maipai_body.link.state import StateReporter
from maipai_body.link.state_machine import LinkPhase, LinkStateMachine
from maipai_body.run_loop import LINK_RESTORED_LINE, FunnelState
from maipai_body.speech.stt_stream import SttStreamResult
from maipai_body.speech.turn_client import TurnLinkLost
from maipai_body.speech.wake import WakeEvent
from tests.ladder_fakes import FakeClock, FakeSpeaker
from tests.test_run_loop import _make_loop, _start, _stop, _wait_for

UTC = datetime.UTC
N = 600.0


class _Volume:
    def __init__(self) -> None:
        self.level = 50

    def get_level(self) -> int:
        return self.level

    def set_level(self, level: int) -> None:
        self.level = level


class _Recognizer:
    """The fake keyword spotter: returns the next scripted phrase per listen."""

    def __init__(self, phrases) -> None:
        self.phrases = list(phrases)
        self.listens = 0

    def listen(self, capture, stop_event):
        self.listens += 1
        return self.phrases.pop(0) if self.phrases else None


def _rungs(*, phrases=(), recognizer=True, speaker=None, clock=None):
    clock = clock or FakeClock()
    machine = LinkStateMachine(clock=clock, wall_clock=clock.wall_clock, sleep_after_s=N)
    volume = _Volume()
    speaker = speaker if speaker is not None else FakeSpeaker()
    rung0 = Rung0Cues(
        render=lambda p: True,
        machine=machine,
        clock=clock,
        settings=Rung0Settings(away_after_s=120.0, tracking_off_after_s=300.0),
        speaker=speaker,
    )
    offline = OfflineRungs(
        machine=machine,
        rung0=rung0,
        recognizer=_Recognizer(phrases) if recognizer else None,
        router=CommandRouter(
            volume=volume,
            timers=LocalTimers(clock),
            machine=machine,
            wall_clock=clock.wall_clock,
            tz=UTC,
        ),
        speaker=speaker,
        gate=ReplayGate(lambda item: None, accepting=False),
        tz=UTC,
    )
    return offline, clock, volume, speaker


def _run_one_wake(loop):
    stop_event, thread = _start(loop)
    _wait_for(lambda: loop._wake.poll_count >= 2 and loop._capture.poll_count >= 2)
    time.sleep(0.15)  # let the wake be handled
    _stop(stop_event, thread)


# ---- the funnel tells the machine -------------------------------------------------------------


def test_a_turn_lost_to_the_link_moves_the_machine_to_reconnecting():
    offline, *_ = _rungs()
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="hello"),
        turn_raises=TurnLinkLost("wifi gone"),
        offline=offline,
    )
    stop_event, thread = _start(loop)
    _wait_for(lambda: offline.machine.phase is LinkPhase.RECONNECTING)
    _stop(stop_event, thread)
    assert "wifi gone" in offline.machine.snapshot().last_error


def test_a_lost_speech_stream_moves_the_machine_too():
    offline, *_ = _rungs()
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="hello"),
        offline=offline,
    )

    def broken(capture):
        raise requests.ConnectionError("stt socket reset")

    loop._stt.run = broken
    stop_event, thread = _start(loop)
    _wait_for(lambda: offline.machine.phase is LinkPhase.RECONNECTING)
    _stop(stop_event, thread)
    assert "stt socket reset" in offline.machine.snapshot().last_error


def test_a_good_turn_leaves_the_machine_connected():
    from maipai_body.expression.cue import Cue, Phase
    from maipai_body.speech.turn_client import TurnEvent

    offline, *_ = _rungs()
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="hello"),
        turn_events=[
            TurnEvent(
                cue=Cue(phase=Phase.DONE, cue_seq=1),
                reply_text="hi",
                conversation_id="c",
                turn_id="t",
            )
        ],
        offline=offline,
    )
    _run_one_wake(loop)
    assert parts["tts"].speak_calls == ["hi"]
    assert offline.machine.phase is LinkPhase.CONNECTED


# ---- rung 1 during an outage -----------------------------------------------------------------


TIME_CLIPS = ["cmd.time_prefix", "char.0", "char.8", "char.0", "char.0"]


def test_each_rung_1_command_yields_its_fixed_reply_and_never_a_turn():
    cases = [
        ("stop", ["cmd.stopped"], "Stopped."),
        ("quieter", ["cmd.quieter"], "Quieter."),
        ("louder", ["cmd.louder"], "Louder."),
        ("timer", ["cmd.timer_set"], "Timer set."),
        ("what time is it", TIME_CLIPS, "It is 08:00."),
        ("are you connected", ["line.unreachable"], None),
    ]  # fmt: skip
    for phrase, clip_ids, text in cases:
        offline, _clock, _volume, speaker = _rungs(phrases=[phrase])
        offline.machine.link_lost("unreachable: ConnectTimeout")
        loop, parts = _make_loop(
            wake_events=[WakeEvent(score=0.9)],
            stt_result=SttStreamResult(kind="final", text="never used"),
            offline=offline,
        )
        _run_one_wake(loop)
        assert speaker.said == [clip_ids], phrase
        if text is not None:
            assert offline.last_reply.text == text, phrase
        assert parts["stt"].call_count == 0, phrase
        assert parts["turn"].stream_calls == [], phrase
        assert parts["tts"].speak_calls == [], phrase


def test_the_command_effects_reach_the_collaborators():
    offline, _clock, volume, _speaker = _rungs(phrases=["quieter"])
    offline.machine.link_lost("x")
    loop, _ = _make_loop(wake_events=[WakeEvent(score=0.9)], offline=offline)
    _run_one_wake(loop)
    assert volume.level == 40


def test_stop_cuts_playback_and_holds_the_head():
    offline, *_ = _rungs(phrases=["stop"])
    offline.machine.link_lost("x")
    loop, parts = _make_loop(wake_events=[WakeEvent(score=0.9)], offline=offline)
    _run_one_wake(loop)
    assert parts["playback"].stop_calls >= 1
    assert any(c.kind == "hold" for c in parts["client"].sent_commands)


def test_the_funnel_never_leaves_idle_during_an_outage_except_for_a_command():
    # an unrecognised phrase: the funnel never moves at all
    offline, *_ = _rungs(phrases=["tell me a joke", "stop the music please"])
    offline.machine.link_lost("x")
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9), WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="tell me a joke"),
        offline=offline,
    )
    _run_one_wake(loop)
    assert loop.state.trace == []
    assert loop.state.funnel is FunnelState.IDLE
    assert parts["stt"].call_count == 0
    assert parts["turn"].stream_calls == []

    # a command: speaking and back to idle, and nothing else
    offline, *_ = _rungs(phrases=["are you connected"])
    offline.machine.link_lost("x")
    loop, parts = _make_loop(wake_events=[WakeEvent(score=0.9)], offline=offline)
    _run_one_wake(loop)
    assert [t.state for t in loop.state.trace] == [FunnelState.SPEAKING, FunnelState.IDLE]


def test_no_turn_text_is_queued_in_rungs_0_to_2():
    offline, *_ = _rungs(phrases=["what's the weather", "tell me a joke", "stop"])
    offline.machine.link_lost("x")
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)] * 3,
        stt_result=SttStreamResult(kind="final", text="what's the weather"),
        offline=offline,
    )
    stop_event, thread = _start(loop)
    _wait_for(lambda: offline.recognizer.listens >= 3)
    _stop(stop_event, thread)
    assert offline.gate.pending == ()
    assert offline.gate.accepting is False
    assert offline.gate.refused == 2  # the two phrases outside the list, counted, never kept
    assert parts["turn"].stream_calls == []
    assert "Nothing is saved for later." in offline.status_text()


def test_with_no_recognizer_wired_a_wake_during_an_outage_runs_no_turn_but_is_not_silent():
    offline, _clock, _volume, speaker = _rungs(recognizer=False)
    offline.machine.link_lost("x")
    loop, parts = _make_loop(wake_events=[WakeEvent(score=0.9)], offline=offline)
    _run_one_wake(loop)
    assert [t.state for t in loop.state.trace] == [FunnelState.SPEAKING, FunnelState.IDLE]
    assert speaker.said == [["line.unreachable"]]
    assert parts["stt"].call_count == 0
    assert parts["turn"].stream_calls == []


def test_unrendered_clips_leave_the_reply_visible_but_unspoken():
    speaker = FakeSpeaker(available=set())
    offline, *_ = _rungs(phrases=["what time is it"], speaker=speaker)
    offline.machine.link_lost("x")
    loop, _ = _make_loop(wake_events=[WakeEvent(score=0.9)], offline=offline)
    _run_one_wake(loop)
    assert speaker.said == []
    assert offline.last_reply.text == "It is 08:00."


def test_connected_wakes_still_run_a_normal_hub_turn():
    offline, *_ = _rungs(phrases=["stop"])
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="hello"),
        offline=offline,
    )
    _run_one_wake(loop)
    assert parts["stt"].call_count == 1
    assert offline.recognizer.listens == 0


# ---- the state frame and the reporter -------------------------------------------------------


def test_the_snapshot_reports_the_ladder_phase_while_the_funnel_is_idle():
    offline, clock, *_ = _rungs()
    loop, _ = _make_loop(offline=offline)
    assert loop.snapshot()["activity"] == "idle"
    offline.machine.link_lost("x")
    assert loop.snapshot()["activity"] == "reconnecting"
    clock.advance(N)
    offline.machine.tick()
    assert loop.snapshot()["activity"] == "sleeping"
    offline.machine.redeemed("lan", None)
    assert loop.snapshot()["activity"] == "idle"


def test_the_existing_state_reporter_publishes_reconnecting_then_sleeping():
    offline, clock, *_ = _rungs()
    change = threading.Event()
    loop, _ = _make_loop(offline=offline, on_change=change.set)
    session = Mock(spec=requests.Session)
    session.put.return_value = Mock(status_code=204)
    stop_event = threading.Event()
    reporter = StateReporter(
        lambda: ("cookie", "https://hub.example.test"),
        stop_event,
        loop.snapshot,
        change,
        interval_s=60.0,
        session=session,
    )
    thread = threading.Thread(target=reporter.run, daemon=True)
    thread.start()
    _wait_for(lambda: session.put.call_count >= 1)
    offline.machine.link_lost("x")  # the machine's edge sets the change event
    _wait_for(lambda: session.put.call_count >= 2)
    clock.advance(N)
    offline.machine.tick()
    _wait_for(lambda: session.put.call_count >= 3)
    stop_event.set()
    thread.join(timeout=2.0)
    activities = [c.kwargs["json"]["activity"] for c in session.put.call_args_list]
    assert activities[:3] == ["idle", "reconnecting", "sleeping"]


# ---- rung 0 in the loop ---------------------------------------------------------------------


def _face_loop(offline):
    loop, parts = _make_loop(offline=offline, presence_interval_s=0.01)
    parts["client"].face_target = FaceTrackTarget(detected=True, x=0.0, y=0.0)
    return loop, parts


def test_tracking_goes_off_after_the_configured_time_in_an_outage():
    offline, clock, *_ = _rungs()
    offline.machine.link_lost("x")
    loop, parts = _face_loop(offline)
    stop_event, thread = _start(loop)
    _wait_for(lambda: loop.state.tracking is True)
    clock.advance(300.0)
    _wait_for(lambda: loop.state.tracking is False)
    time.sleep(0.1)
    assert loop.state.tracking is False  # and it stays off while a face is still there
    _stop(stop_event, thread)


def test_tracking_never_starts_while_sleeping():
    offline, clock, *_ = _rungs()
    offline.machine.link_lost("x")
    clock.advance(N)
    offline.machine.tick()
    loop, parts = _face_loop(offline)
    stop_event, thread = _start(loop)
    time.sleep(0.2)
    assert loop.state.tracking is False
    _stop(stop_event, thread)


def test_the_loop_gives_the_rung_0_cues_the_engine_and_the_funnel_gate():
    offline, clock, *_ = _rungs()
    loop, parts = _make_loop(offline=offline)
    offline.machine.link_lost("x")
    offline.rung0.tick()  # the loop attached its own render and gate
    assert parts["engine"].ambient == ["settle", "breathe"]
    assert parts["client"].sent_commands
    assert {c.kind for c in parts["client"].sent_commands} == {"set_target"}


# ---- the reconnect and the owed line --------------------------------------------------------


def test_a_spoken_reconnect_clip_replaces_the_owed_hub_line():
    offline, clock, _volume, speaker = _rungs()
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="hello"),
        turn_raises=TurnLinkLost("wifi gone"),
        offline=offline,
    )
    stop_event, thread = _start(loop)
    _wait_for(lambda: offline.machine.phase is LinkPhase.RECONNECTING)
    _stop(stop_event, thread)
    assert loop._lost_turn_unannounced is True

    offline.machine.redeemed("lan", None)
    offline.rung0.tick()

    assert speaker.said == [["line.reconnect"]]
    assert loop._lost_turn_unannounced is False
    assert LINK_RESTORED_LINE  # still the fallback when the clip cannot be spoken


def test_without_a_speakable_clip_the_hub_line_is_still_owed():
    speaker = FakeSpeaker(available=set())
    offline, *_ = _rungs(speaker=speaker)
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="hello"),
        turn_raises=TurnLinkLost("wifi gone"),
        offline=offline,
    )
    stop_event, thread = _start(loop)
    _wait_for(lambda: offline.machine.phase is LinkPhase.RECONNECTING)
    _stop(stop_event, thread)
    offline.machine.redeemed("lan", None)
    offline.rung0.tick()
    assert loop._lost_turn_unannounced is True


def test_a_fired_timer_stirs_the_body_and_says_the_done_clip_if_it_can():
    speaker = FakeSpeaker()
    offline, *_ = _rungs(speaker=speaker)
    loop, parts = _make_loop(offline=offline)
    offline.timer_due()
    assert speaker.said == [["cmd.timer_done"]]
    assert parts["engine"].ambient == ["perk", "settle"]

    quiet = FakeSpeaker(available=set())
    offline, *_ = _rungs(speaker=quiet)
    _make_loop(offline=offline)
    offline.timer_due()
    assert quiet.said == []
