"""VOICE-02: a stop word over playback cuts locally, cancels, keeps the prefix."""

from __future__ import annotations

import threading

import pytest

from maipai_body.speech.barge import TranscriptStopDetector, is_stop_phrase
from tests.test_speech_process import build
from tests.voice_fakes import HitAfter, LevelVad, ScriptedStt, silence, speech, wake_blocks

LONG = "One two three four. Five six seven eight. Nine ten eleven twelve."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("stop", True),
        ("Stop!", True),
        ("okay stop that", True),
        ("quiet", True),
        ("please stop talking right now", False),  # five words: a sentence, not a command
        ("the bus stop is on main street", False),
        ("", False),
        ("go on", False),
    ],
)
def test_stop_phrase_list_is_closed(text, expected):
    assert is_stop_phrase(text) is expected


def test_a_stop_word_cuts_playback_within_one_block_and_cancels():
    detector = HitAfter(10)
    proc, _, _, _, recorder, _ = build(silence(500), with_voice=True, stop=detector, timed=True)
    cancelled: list[str] = []
    record = proc.speak(LONG, turn_id="t9", on_barge=lambda: cancelled.append("t9"))
    assert record.cancelled and not record.completed
    assert record.cancel_reason == "stop_word"
    assert cancelled == ["t9"]
    # Detection came on the 10th captured block (0.32 s). The cut is that block,
    # and what played is never more than what the clock let through.
    assert recorder.events[-1] == "stop"
    assert 0.32 - 0.032 <= record.heard_s <= 0.32 + 0.032
    assert (
        record.spoken_prefix == "One two"
    )  # 0.32 s of a 0.5 s, 4-word sentence: 2.56 words, rounded down
    assert LONG.startswith(record.spoken_prefix)


def test_the_prefix_never_claims_unplayed_words():
    detector = HitAfter(20)  # 0.64 s in: one 0.5 s sentence plus 0.14 s of the next
    proc, *_ = build(silence(500), with_voice=True, stop=detector, timed=True)
    record = proc.speak(LONG)
    assert record.spoken_prefix.startswith("One two three four.")
    assert "Nine" not in record.spoken_prefix
    assert len(record.spoken_prefix.split()) <= 5


def test_a_reply_nobody_interrupts_completes_with_no_cancel():
    proc, *_ = build(silence(500), with_voice=True, stop=HitAfter(10_000), timed=True)
    called: list[int] = []
    record = proc.speak("Hello there.", on_barge=lambda: called.append(1))
    assert record.completed and not record.cancelled and called == []


def test_an_external_stop_event_cuts_too():
    proc, *_ = build(silence(500), with_voice=True)
    event = threading.Event()
    event.set()
    record = proc.speak(LONG, stop_event=event)
    assert record.cancelled and record.cancel_reason == "stop_event"
    assert record.spoken_prefix == ""


def test_a_failing_cancel_callback_does_not_unwind_the_local_cut():
    proc, *_ = build(silence(500), with_voice=True, stop=HitAfter(3), timed=True)

    def boom() -> None:
        raise RuntimeError("runtime down")

    record = proc.speak(LONG, on_barge=boom)
    assert record.cancelled


def test_transcript_detector_fires_on_a_spoken_stop_at_the_end_of_the_span():
    stt = ScriptedStt("stop")
    detector = TranscriptStopDetector(LevelVad(), stt)
    results = [detector.accept(b) for b in silence(5) + speech(6) + silence(12)]
    assert results.count(True) == 1
    assert results.index(True) >= 5 + 6  # not before the word has been heard
    assert len(stt.calls) == 1


def test_transcript_detector_ignores_other_speech_and_a_failing_engine():
    detector = TranscriptStopDetector(LevelVad(), ScriptedStt("what a lovely day it is"))
    assert not any(detector.accept(b) for b in speech(6) + silence(12))

    class Boom(ScriptedStt):
        def transcribe(self, samples, sample_rate):
            raise RuntimeError("x")

    detector = TranscriptStopDetector(LevelVad(), Boom())
    assert not any(detector.accept(b) for b in speech(6) + silence(12))


def test_transcript_detector_end_to_end_over_playback():
    # A person says "stop" 0.2 s into the reply (blocks 7..12 of the capture).
    blocks = silence(6) + speech(6) + silence(400)
    detector = TranscriptStopDetector(LevelVad(), ScriptedStt("stop"))
    proc, _, _, _, recorder, _ = build(blocks, with_voice=True, stop=detector, timed=True)
    record = proc.speak(LONG)
    assert record.cancel_reason == "stop_word"
    assert len(recorder.chunks) < 40  # cut well inside the 1.5 s reply, no tail played


def test_zero_self_wakes_with_the_echo_looped_into_the_capture():
    # The mic hears the robot's own reply at wake-word level for the whole reply.
    proc, capture, _, engine, _, _ = build(wake_blocks(200), with_voice=True, timed=True)
    record = proc.speak(LONG)
    assert record.completed
    assert proc.self_wakes == 0 and not proc.listening and engine.resets == 0
