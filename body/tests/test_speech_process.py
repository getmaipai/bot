"""VOICE-01: the speech process over scripted blocks and the fake body."""

from __future__ import annotations

import numpy as np

from maipai_body.bodies.reachy_mini.fake import (
    FakeReachyMiniClient,
    LoopbackRecorder,
    ManualClock,
)
from maipai_body.hal.seam import DirectionOfArrival
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.process import (
    MAX_UTTERANCE_S,
    SegmentRecord,
    SpeechProcess,
    spoken_prefix,
)
from maipai_body.speech.wake import WakeScorer
from tests.voice_fakes import (
    LevelVad,
    LevelWakeEngine,
    ScriptedCapture,
    ScriptedStt,
    ScriptedTts,
    seconds,
    silence,
    speech,
    wake_blocks,
)


def build(blocks, *answers, doa=None, with_voice=False, stop=None, normalizer=None, timed=False):
    clock = ManualClock()
    recorder = LoopbackRecorder(clock=clock)
    client = FakeReachyMiniClient(
        clock=clock,
        recorder=recorder,
        doa_script=[(0.0, doa, True)] if doa is not None else None,
    )
    capture = ScriptedCapture(blocks, clock if timed else None)
    engine = LevelWakeEngine()
    stt = ScriptedStt(*answers)
    proc = SpeechProcess(
        audio=client,
        capture=capture,  # type: ignore[arg-type]
        wake=WakeScorer(engine, client),
        vad=LevelVad(),
        stt=stt,
        playback=AudioPlayback(client) if with_voice else None,
        tts=ScriptedTts() if with_voice else None,
        stop_detector=stop,
        normalizer=normalizer,
        clock=clock,
        sleep=clock.advance,
    )
    return proc, capture, stt, engine, recorder, clock


def run_until_quiet(proc, capture, limit=2000):
    events = []
    for _ in range(limit):
        if capture.exhausted:
            break
        events.extend(proc.step())
    return events


def kinds(events):
    return [e.kind for e in events]


def test_wake_then_sentence_gives_one_utterance_with_doa():
    blocks = silence(5) + wake_blocks(1) + silence(3) + speech(20) + silence(30)
    proc, capture, stt, _, _, _ = build(blocks, "turn on the lights", doa=1.25)
    events = run_until_quiet(proc, capture)
    assert kinds(events) == ["wake", "speech_start", "speech_end", "utterance"]
    utterance = events[-1]
    assert utterance.text == "turn on the lights"
    assert utterance.doa == DirectionOfArrival(angle_rad=1.25, speech_detected=True)
    assert utterance.speech_s is not None and abs(utterance.speech_s - 20 * 0.032) < 1e-6
    assert not proc.listening


def test_nothing_before_the_wake_word_reaches_stt():
    proc, capture, stt, _, _, _ = build(speech(40) + silence(40))
    # Speech at a level the wake engine does not score: never wakes.
    assert run_until_quiet(proc, capture) == []
    assert stt.calls == []


def test_preroll_trims_the_silent_head_while_waiting():
    # 1.5 s of silence after the wake word, then speech: the transcribed audio
    # must start within the pre-roll (0.3 s) of the onset, not 1.5 s earlier.
    blocks = wake_blocks(1) + silence(seconds(1.5)) + speech(15) + silence(30)
    proc, capture, stt, _, _, _ = build(blocks, "hello")
    run_until_quiet(proc, capture)
    first = stt.calls[0]
    head_s = float(np.argmax(np.abs(first) > 0.1)) / 16000
    assert head_s <= 0.3 + 0.032


def test_empty_transcript_retries_once_from_the_onset_block():
    blocks = wake_blocks(1) + silence(seconds(0.3)) + speech(15) + silence(30)
    proc, capture, stt, _, _, _ = build(blocks, "", "set a timer")
    events = run_until_quiet(proc, capture)
    assert len(stt.calls) == 2
    assert len(stt.calls[1]) < len(stt.calls[0])
    assert stt.calls[1][0] != 0.0  # the retry starts on speech, not on the silent head
    assert events[-1].kind == "utterance" and events[-1].text == "set a timer"


def test_tail_syllable_false_start_keeps_listening():
    # The wake phrase's tail trips the VAD, then a pause closes a "turn" with
    # nothing in it. The real sentence follows inside the patience window.
    blocks = wake_blocks(1) + speech(4) + silence(30) + speech(20) + silence(30)
    proc, capture, stt, _, _, _ = build(blocks, "", "", "what time is it")
    events = run_until_quiet(proc, capture)
    assert "utterance" in kinds(events)
    assert events[-1].text == "what time is it"
    notes = [e.note for e in events if e.kind == "no_speech"]
    assert notes and all("still listening" in (n or "") for n in notes)


def test_patience_bounds_the_false_start_window():
    blocks = wake_blocks(1) + speech(4) + silence(seconds(7))
    proc, capture, _, _, _, _ = build(blocks, "")
    events = run_until_quiet(proc, capture)
    assert events[-1].kind == "no_speech"
    assert not proc.listening


def test_woken_then_silence_gives_no_speech_after_patience():
    blocks = wake_blocks(1) + silence(seconds(7))
    proc, capture, stt, engine, _, _ = build(blocks)
    events = run_until_quiet(proc, capture)
    assert kinds(events) == ["wake", "no_speech"]
    assert stt.calls == []
    assert engine.resets >= 1  # the phrase that woke us cannot wake us again


def test_a_hard_cap_ends_an_endless_noise():
    blocks = wake_blocks(1) + speech(seconds(MAX_UTTERANCE_S) + 20)
    proc, capture, _, _, _, _ = build(blocks, "a very long sentence")
    events = run_until_quiet(proc, capture)
    assert events[-1].kind == "utterance"


def test_transcription_error_is_no_speech_not_a_crash():
    class Boom(ScriptedStt):
        def transcribe(self, samples, sample_rate):
            raise RuntimeError("model gone")

    blocks = wake_blocks(1) + speech(10) + silence(30)
    proc, capture, _, _, _, _ = build(blocks)
    proc._stt = Boom()
    events = run_until_quiet(proc, capture)
    assert events[-1].kind == "no_speech" and "failed" in events[-1].note


def test_listen_again_opens_the_window_without_a_wake_word():
    blocks = speech(10) + silence(30)
    proc, capture, _, _, _, _ = build(blocks, "yes please")
    proc.listen_again(patience_s=4.0)
    events = run_until_quiet(proc, capture)
    assert events[-1].kind == "utterance" and events[-1].text == "yes please"


def test_last_utterance_stays_in_ram_only_and_is_replaced():
    blocks = wake_blocks(1) + speech(10) + silence(30)
    proc, capture, _, _, _, _ = build(blocks, "one")
    run_until_quiet(proc, capture)
    assert proc.last_utterance is not None and proc.last_utterance.size > 0


def test_last_utterance_is_cropped_to_the_speech_span():
    blocks = wake_blocks(1) + silence(3) + speech(20) + silence(30)
    proc, capture, _, _, _, _ = build(blocks, "one two")
    run_until_quiet(proc, capture)
    assert proc.last_utterance is not None
    assert proc.last_utterance.size == 20 * 512


# -- speaking and the ledger ---------------------------------------------------


def test_speak_plays_every_sentence_and_records_the_row():
    proc, _, _, _, recorder, clock = build([], with_voice=True)
    record = proc.speak("Hello there. How are you.", turn_id="t1")
    assert record.completed and not record.cancelled
    assert record.spoken_prefix == "Hello there. How are you."
    assert [s.text for s in record.segments] == ["Hello there.", "How are you."]
    assert abs(record.heard_s - 1.0) < 0.05
    assert abs(clock() - 1.0) < 0.2  # paced to the clock, not dumped at once
    assert recorder.total_frames == round(16000 * record.heard_s)
    assert proc.spoken_ledger == [record] and record.turn_id == "t1"
    assert record.voice_id == "voice-test"


def test_speak_runs_the_normalizer_before_synthesis():
    proc, _, _, _, _, _ = build(
        [], with_voice=True, normalizer=lambda t: t.replace("Dr.", "Doctor")
    )
    record = proc.speak("Dr. Smith is here")
    assert record.text == "Doctor Smith is here"
    assert proc.tts.texts == ["Doctor Smith is here"]  # type: ignore[union-attr]


def test_speak_without_a_voice_says_so():
    proc, *_ = build([])
    try:
        proc.speak("hi")
    except RuntimeError as exc:
        assert "no playback or voice" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")


def test_the_wake_scorer_is_not_fed_while_speaking():
    # The robot's own echo (here wake-level blocks in the capture) must not wake it.
    proc, capture, _, engine, _, _ = build(wake_blocks(80), with_voice=True)
    proc.speak("Hello there. How are you.")
    assert proc.self_wakes == 0
    assert not proc.listening
    assert engine.resets == 0


def test_spoken_prefix_rounds_down_to_whole_words():
    segs = [SegmentRecord("One two.", 1.0), SegmentRecord("Three four five six.", 2.0)]
    assert spoken_prefix(segs, 0.0) == ""
    assert spoken_prefix(segs, 0.49) == ""
    assert spoken_prefix(segs, 0.5) == "One"
    assert spoken_prefix(segs, 1.0) == "One two."
    assert spoken_prefix(segs, 2.0) == "One two. Three four"
    assert spoken_prefix(segs, 3.0) == "One two. Three four five six."
