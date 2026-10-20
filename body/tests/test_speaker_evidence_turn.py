"""SPEAK-02 / SPEAK-04: the turn carries `speaker_evidence` and `present`, fused
from the voice gallery and the face watch, and a sensitive reply is rechecked
as it is spoken. Scripted stand-ins, like tests/test_run_loop.py."""

from __future__ import annotations

import numpy as np
import pytest

from maipai_body.expression.cue import Cue, Phase
from maipai_body.speaker_evidence import speaker_evidence
from maipai_body.speech.stt_stream import SttStreamResult
from maipai_body.speech.wake import WakeEvent
from maipai_body.vision.gallery import FaceVerdict
from maipai_body.vision.watch import WatchSnapshot
from tests.test_run_loop import (
    _make_loop,
    _start,
    _stop,
    _wait_for,
    _wait_for_idle_after_turn,
)

ANNA = "person-anna01"
BEN = "person-ben002"


class _Voice:
    """A VoiceIdentifier stand-in: a fixed answer and a fixed present list."""

    def __init__(self, answer, present=()):
        self.answer = answer
        self.roster = list(present)
        self.heard = []

    def evidence(self, pcm, *, speech_s, doa=None, now=0.0):
        self.heard.append((len(pcm), speech_s))
        return self.answer

    def present(self, *, now):
        return list(self.roster)


class _Watch:
    def __init__(self, present=0, verdict=None):
        self.snapshot = WatchSnapshot(level="on", present=present, verdict=verdict)
        self.device_level = "on"

    def current(self):
        return self.snapshot

    def set_device_level(self, level):
        self.device_level = level

    def run(self, stop_event):
        stop_event.wait()


def _final():
    return SttStreamResult(
        kind="final", text="what is on my list", audio=np.zeros(16000, "float32"), speech_s=1.2
    )


def _reply():
    from maipai_body.speech.turn_client import TurnEvent

    return [
        TurnEvent(
            cue=Cue(phase=Phase.DONE, cue_seq=1),
            reply_text="hi",
            conversation_id="c1",
            turn_id="t1",
        )
    ]


def _run_one(**kw):
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)], stt_result=_final(), turn_events=_reply(), **kw
    )
    stop, thread = _start(loop)
    try:
        _wait_for_idle_after_turn(loop)
        _wait_for(lambda: bool(parts["turn"].speaker_evidence_calls))
    finally:
        _stop(stop, thread)
    return loop, parts


def test_no_identity_machinery_sends_no_evidence():
    loop, parts = _run_one()
    assert parts["turn"].speaker_evidence_calls == [None]


def test_a_confirmed_voice_is_the_speaker_and_the_audio_reaches_the_embedder():
    voice = _Voice(
        speaker_evidence(ANNA, "voice", "confirmed"), [speaker_evidence(ANNA, "voice", "confirmed")]
    )
    loop, parts = _run_one(voice_identifier=voice)
    assert parts["turn"].speaker_evidence_calls == [
        {"person": ANNA, "basis": "voice", "level": "confirmed"}
    ]
    assert voice.heard == [(16000, 1.2)]


def test_voice_and_face_agreeing_is_confirmed_on_both():
    voice = _Voice(
        speaker_evidence(ANNA, "voice", "tentative"), [speaker_evidence(ANNA, "voice", "tentative")]
    )
    watch = _Watch(1, FaceVerdict(person_id=ANNA, level="tentative", score=0.9))
    loop, parts = _run_one(voice_identifier=voice, vision_watch=watch)
    assert parts["turn"].speaker_evidence_calls == [
        {"person": ANNA, "basis": "voice_and_face", "level": "confirmed"}
    ]


def test_a_voice_and_a_face_that_name_different_people_are_unknown():
    voice = _Voice(speaker_evidence(ANNA, "voice", "confirmed"))
    watch = _Watch(1, FaceVerdict(person_id=BEN, level="confirmed", score=0.9))
    loop, parts = _run_one(voice_identifier=voice, vision_watch=watch)
    assert parts["turn"].speaker_evidence_calls == [
        {"person": None, "basis": "unknown", "level": "unknown"}
    ]


def test_two_faces_in_view_do_not_lend_the_speaker_a_face():
    voice = _Voice(speaker_evidence(None, "unknown", "unknown"))
    watch = _Watch(2, FaceVerdict(person_id=ANNA, level="confirmed", score=0.9))
    loop, parts = _run_one(voice_identifier=voice, vision_watch=watch)
    assert parts["turn"].speaker_evidence_calls == [
        {"person": None, "basis": "unknown", "level": "unknown"}
    ]


def test_a_claim_is_tentative_never_access_and_lasts_one_turn():
    voice = _Voice(speaker_evidence(None, "unknown", "unknown"))
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9), WakeEvent(score=0.9)],
        stt_result=_final(),
        turn_events=_reply(),
        voice_identifier=voice,
    )
    loop.claim_speaker(ANNA)
    stop, thread = _start(loop)
    try:
        _wait_for(lambda: len(parts["turn"].speaker_evidence_calls) >= 2, timeout=20.0)
    finally:
        _stop(stop, thread)
    first, second = parts["turn"].speaker_evidence_calls[:2]
    assert first == {"person": ANNA, "basis": "claimed", "level": "tentative"}
    assert second == {"person": None, "basis": "unknown", "level": "unknown"}


def test_a_claim_an_enrolled_voice_contradicts_is_unknown():
    voice = _Voice(speaker_evidence(BEN, "voice", "confirmed"))
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=_final(),
        turn_events=_reply(),
        voice_identifier=voice,
    )
    loop.claim_speaker(ANNA)
    stop, thread = _start(loop)
    try:
        _wait_for(lambda: bool(parts["turn"].speaker_evidence_calls))
    finally:
        _stop(stop, thread)
    assert parts["turn"].speaker_evidence_calls == [
        {"person": None, "basis": "unknown", "level": "unknown"}
    ]


def test_a_malformed_claim_is_refused():
    loop, _ = _make_loop()
    with pytest.raises(ValueError):
        loop.claim_speaker("anna")


def test_snapshot_without_an_utterance_uses_face_and_recent_voices():
    voice = _Voice(None, [speaker_evidence(BEN, "voice", "tentative")])
    watch = _Watch(1, FaceVerdict(person_id=ANNA, level="confirmed", score=0.9))
    loop, _ = _make_loop(voice_identifier=voice, vision_watch=watch)
    evidence, present = loop.speaker_snapshot()
    assert evidence == {"person": ANNA, "basis": "face", "level": "tentative"}
    assert {(p["person"], p["basis"]) for p in present} == {(BEN, "voice"), (ANNA, "face")}


def test_a_sensitive_reply_stops_when_someone_walks_in_while_it_is_spoken():
    voice = _Voice(
        speaker_evidence(ANNA, "voice", "confirmed"), [speaker_evidence(ANNA, "voice", "confirmed")]
    )
    watch = _Watch(1, FaceVerdict(person_id=ANNA, level="confirmed", score=0.9))
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=_final(),
        turn_events=_reply(),
        tts_behavior="hang_until_stop",
        voice_identifier=voice,
        vision_watch=watch,
        audience_check_interval_s=0.01,
    )
    primitives: list[str] = []
    real = parts["engine"].render_primitive
    parts["engine"].render_primitive = lambda name, ctx, **kw: (
        primitives.append(name) or real(name, ctx, **kw)
    )
    stop, thread = _start(loop)
    try:
        _wait_for(lambda: bool(parts["tts"].speak_calls))
        watch.snapshot = WatchSnapshot(level="on", present=2, verdict=watch.snapshot.verdict)
        _wait_for_idle_after_turn(loop)
    finally:
        _stop(stop, thread)
    assert parts["turn"].cancel_calls == ["t1"]
    assert parts["playback"].flush_calls >= 1
    assert "settle" in primitives


def test_a_reply_to_someone_not_alone_is_not_guarded_and_plays_through():
    # Unknown speaker: sensitive records were never allowed, so there is nothing to recheck.
    voice = _Voice(speaker_evidence(None, "unknown", "unknown"))
    loop, parts = _run_one(voice_identifier=voice)
    assert parts["turn"].cancel_calls == []


def test_present_lists_the_speaker_and_a_visitor_so_the_speaker_is_not_alone():
    voice = _Voice(
        speaker_evidence(ANNA, "voice", "confirmed"), [speaker_evidence(ANNA, "voice", "confirmed")]
    )
    watch = _Watch(2, FaceVerdict(person_id=ANNA, level="confirmed", score=0.9))
    loop, parts = _run_one(voice_identifier=voice, vision_watch=watch)
    (present,) = parts["turn"].present_calls
    assert {"person": ANNA, "basis": "voice_and_face", "level": "confirmed"} in present
    assert {"person": None, "basis": "face", "level": "unknown"} in present
    assert len(present) == 2


def test_present_alone_is_exactly_the_speaker():
    voice = _Voice(
        speaker_evidence(ANNA, "voice", "confirmed"), [speaker_evidence(ANNA, "voice", "confirmed")]
    )
    loop, parts = _run_one(voice_identifier=voice)
    assert parts["turn"].present_calls == [
        [{"person": ANNA, "basis": "voice", "level": "confirmed"}]
    ]


def test_an_unknown_voice_with_nobody_in_view_still_counts_one_unknown_present():
    voice = _Voice(speaker_evidence(None, "unknown", "unknown"))
    loop, parts = _run_one(voice_identifier=voice)
    assert parts["turn"].present_calls == [[{"person": None, "basis": "voice", "level": "unknown"}]]
