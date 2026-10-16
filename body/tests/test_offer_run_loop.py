"""OFFER-01 through the real run loop: the accepted offer skips STT and opens
one turn that carries the offer id, the heard phrase and the face evidence."""

from __future__ import annotations

import threading
import time

from maipai_body.expression.cue import Cue, Phase
from maipai_body.speech.turn_client import TurnEvent
from maipai_body.vision.gallery import FaceVerdict
from tests.test_offer import ScriptedEngine
from tests.test_run_loop import _make_loop


def _done_events():
    return [
        TurnEvent(cue=Cue(phase=Phase.DONE, cue_seq=1), reply_text="on it", turn_id="t1"),
    ]


def _loop(engine=None):
    return _make_loop(turn_events=_done_events(), offer_engine=engine)


def _see(loop, person):
    with loop._lock:
        loop._state.face_verdict = FaceVerdict(person_id=person, level="tentative", score=0.9)
        loop._state.face_verdict_at = time.monotonic()


def test_accept_runs_one_turn_without_stt_and_carries_the_offer():
    engine = ScriptedEngine()
    loop, parts = _loop(engine)
    _see(loop, "person-abc123")
    seen = {}
    original = parts["turn"].stream

    def spy(text, *, speaker_evidence=None, **kwargs):
        seen.update(text=text, evidence=speaker_evidence, kwargs=kwargs)
        return original(text, speaker_evidence=speaker_evidence)

    parts["turn"].stream = spy
    loop._run_stop = threading.Event()
    assert loop.offer.receive(
        {"offer_id": "of_1", "person_id": "person-abc123", "tier": "ask"}
    ) == {"offer": "queued"}
    assert loop.offer.service() is True
    engine.tags.append("@go_ahead")
    assert loop.offer.service() is False
    assert seen["text"] == "go ahead"
    assert seen["kwargs"] == {"ask_answer": {"offer_id": "of_1", "approved": True}}
    assert seen["evidence"] == {"person": "person-abc123", "basis": "face", "level": "tentative"}
    assert parts["stt"].call_count == 0
    assert parts["engine"].ambient[0] == "offer"


def test_no_spotter_refuses_and_a_child_in_the_room_refuses():
    loop, _ = _loop(None)
    assert loop.offer.receive({"offer_id": "o", "person_id": "usr_a"})["reason"] == "no_spotter"
    from maipai_body.presence.carry_reaction import PresenceEntry

    loop2, _ = _make_loop(
        turn_events=_done_events(),
        offer_engine=ScriptedEngine(),
        presence_entries=lambda: [PresenceEntry("adult"), PresenceEntry("child")],
    )
    assert loop2.offer.receive({"offer_id": "o", "person_id": "usr_a"})["reason"] == (
        "child_present"
    )


def test_offer_is_deferred_mid_turn_and_wrong_person_is_not_attentive():
    from maipai_body.run_loop import FunnelState

    engine = ScriptedEngine()
    loop, parts = _loop(engine)
    loop._run_stop = threading.Event()
    _see(loop, "person-def456")
    loop.offer.receive({"offer_id": "o", "person_id": "person-abc123"})
    assert loop.offer.service() is False  # not the person in front
    _see(loop, "person-abc123")
    loop._enter(FunnelState.THINKING)
    assert loop.offer.service() is False  # mid-turn
    assert "offer" not in getattr(parts["engine"], "ambient", [])
    loop._enter(FunnelState.IDLE)
    assert loop.offer.service() is True
