"""FOLLOWUP-01: the follow-up window without the wake word, decided from the
speaker's evidence and the person's band and switch, never the utterance."""

from __future__ import annotations

from maipai_body.speaker_evidence import speaker_evidence
from maipai_body.speech.follow_up import FollowUpPolicy, PeopleDirectory
from maipai_body.speech.wake import WakeEvent
from tests.test_run_loop import _make_loop, _start, _stop, _wait_for
from tests.test_speaker_evidence_turn import ANNA, _final, _reply, _Voice

KID = "person-kid003"


def _policy(**people):
    directory = PeopleDirectory()
    for person, (band, switch) in people.items():
        directory.update(person, band=band, follow_up=switch)
    return FollowUpPolicy(directory, seconds=8)


def _ev(person, level="confirmed", basis="voice"):
    return speaker_evidence(person, basis, level)


def test_an_adult_gets_the_window_by_default():
    assert _policy(**{ANNA: ("adult", None)}).window(_ev(ANNA)) == 8


def test_a_person_can_switch_it_off():
    assert _policy(**{ANNA: ("adult", False)}).window(_ev(ANNA)) == 0


def test_a_child_gets_it_only_when_a_parent_turned_it_on():
    assert _policy(**{KID: ("child", None)}).window(_ev(KID)) == 0
    assert _policy(**{KID: ("child", True)}).window(_ev(KID)) == 8


def test_an_unknown_speaker_never_gets_it():
    policy = _policy(**{ANNA: ("adult", True)})
    assert policy.window(speaker_evidence(None, "unknown", "unknown")) == 0
    assert policy.window(None) == 0


def test_a_claim_is_not_access_to_the_window():
    policy = _policy(**{ANNA: ("adult", None)})
    assert policy.window(speaker_evidence(ANNA, "claimed", "tentative")) == 0


def test_zero_seconds_turns_it_off_and_values_are_clamped():
    policy = _policy(**{ANNA: ("adult", None)})
    policy.set_seconds(0)
    assert policy.window(_ev(ANNA)) == 0
    policy.set_seconds(500)
    assert policy.seconds == 20


def _loop(policy, *, tts="quick"):
    voice = _Voice(_ev(ANNA), [_ev(ANNA)])
    return _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=_final(),
        turn_events=_reply(),
        tts_behavior=tts,
        voice_identifier=voice,
        follow_up=policy,
    )


def test_the_stream_reopens_without_a_wake_and_skips_the_heard_cue():
    loop, parts = _loop(_policy(**{ANNA: ("adult", None)}))
    stop, thread = _start(loop)
    try:
        _wait_for(lambda: parts["stt"].call_count >= 3)
    finally:
        _stop(stop, thread)
    assert parts["stt"].patience_calls[:3] == [None, 8, 8]
    heard = [p for p, _ in parts["engine"].handled if p.name == "HEARD"]
    assert len(heard) == 1  # one wake, one HEARD, however many follow-ups


def test_no_window_means_one_turn_per_wake():
    loop, parts = _loop(_policy(**{ANNA: ("adult", False)}))
    stop, thread = _start(loop)
    try:
        _wait_for(lambda: parts["stt"].call_count >= 1)
        import time

        time.sleep(0.3)
    finally:
        _stop(stop, thread)
    assert parts["stt"].call_count == 1


def test_a_barge_in_does_not_reopen():
    loop, parts = _loop(_policy(**{ANNA: ("adult", None)}), tts="hang_until_stop")
    # a second wake lands while speaking
    parts["wake"]._script.extend([None, WakeEvent(score=0.9)])
    stop, thread = _start(loop)
    try:
        _wait_for(lambda: bool(parts["turn"].cancel_calls))
        import time

        time.sleep(0.3)
    finally:
        _stop(stop, thread)
    assert 8 not in parts["stt"].patience_calls
