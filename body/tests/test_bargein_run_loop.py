"""BARGE-02 in the funnel: the stop word cuts, the tail holds, the open mic is off by default."""

from __future__ import annotations

import threading
import time

import numpy as np

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.expression.cue import Phase
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.wake import WakeEvent
from tests.test_run_loop import _make_loop


class StopOnThird:
    def __init__(self) -> None:
        self.calls = 0
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1

    def accept(self, block) -> bool:
        self.calls += 1
        return self.calls == 3


def run_speak(loop, turn_id="turn-1", generation=7) -> list[bool]:
    out: list[bool] = []
    done = threading.Event()

    def target() -> None:
        out.append(loop._speak("a long story", turn_id, threading.Event(), generation=generation))
        done.set()

    threading.Thread(target=target, daemon=True).start()
    assert done.wait(5.0)
    return out


def test_the_stop_word_cancels_the_turn_flushes_and_renders_cancel() -> None:
    loop, parts = _make_loop(tts_behavior="hang_until_stop")
    loop._stop_detector = StopOnThird()
    run_speak(loop)
    phases = [p for p, _ in parts["engine"].handled]
    assert Phase.CANCEL in phases and Phase.DONE not in phases
    assert parts["turn"].cancel_calls == ["turn-1"]
    assert parts["playback"].flush_calls == 1
    assert parts["wake"].poll_count >= 1  # the wake word stays live beside the stop word
    assert loop._stop_detector.resets == 1


def test_the_reply_is_spoken_with_its_turn_and_generation() -> None:
    loop, parts = _make_loop()
    run_speak(loop)
    assert parts["tts"].speak_tags == {"turn_id": "turn-1", "generation": 7}
    assert parts["playback"].flush_calls == 0  # a finished reply is not flushed


def test_a_wake_still_barges_in_and_now_flushes_too() -> None:
    loop, parts = _make_loop(
        wake_events=[None, WakeEvent(score=0.9)], tts_behavior="hang_until_stop"
    )
    run_speak(loop)
    assert parts["turn"].cancel_calls == ["turn-1"]
    assert parts["playback"].flush_calls == 1


def test_the_capture_is_drained_not_scored_during_the_tail() -> None:
    loop, parts = _make_loop()
    parts["playback"].tail_until = time.monotonic() + 0.3
    seen: dict[str, int] = {}
    original = parts["tts"].speak

    def speak(*a, **kw):
        result = original(*a, **kw)
        seen["wake"] = parts["wake"].poll_count
        return result

    parts["tts"].speak = speak
    start = time.monotonic()
    run_speak(loop)
    assert time.monotonic() - start >= 0.28
    assert parts["wake"].poll_count == seen["wake"]  # the robot's own tail never scored
    assert parts["capture"].poll_count >= 3  # but the mic kept being read
    assert getattr(parts["wake"], "reset_count", 0) == 1


def test_open_mic_is_off_by_default_and_talk_over_needs_the_setting() -> None:
    loud = np.full(512, 0.5, np.float32)
    loop, parts = _make_loop(tts_behavior="hang_until_stop")
    parts["capture"]._block = loud
    parts["playback"].rms = 0.1
    stop = threading.Event()
    # off: a loud mic alone does not cut the reply
    assert loop._barge_trigger(loud, time.monotonic() - 5.0) is False
    loop._open_mic = True
    assert loop._barge_trigger(loud, time.monotonic() - 5.0) is True
    assert loop._barge_trigger(loud, time.monotonic()) is False  # inside the grace
    stop.set()


def test_the_real_playback_tail_after_a_scripted_reply_is_read_from_the_ledger() -> None:
    playback = AudioPlayback(FakeReachyMiniClient())
    playback.push(np.zeros(1600, np.float32))
    assert playback.listen_again_at() > time.monotonic()
