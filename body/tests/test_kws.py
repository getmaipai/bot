"""LINK-STATE-01 rung 1: the keyword-spotter recognizer, on a scripted engine.

The engine is the seam to sherpa-onnx; everything here runs with no model and
no audio. The real model is `test_kws_real_model.py`, gated on a local copy.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from maipai_body.link.commands import COMMAND_PHRASES, LocalCommand, route_phrase
from maipai_body.speech import kws
from maipai_body.speech.capture import BLOCK_DURATION_S

BLOCK = np.zeros(512, dtype=np.float32)


class _Capture:
    """Hands out ``per_call`` blocks per poll, then nothing, like a drained stream."""

    def __init__(self, total_blocks: int, per_call: int = 1) -> None:
        self.left = total_blocks
        self.per_call = per_call
        self.polls = 0

    def poll_blocks(self):
        self.polls += 1
        n = min(self.per_call, self.left)
        self.left -= n
        return [BLOCK] * n


class _Engine:
    """Fires ``tag`` on the ``fire_on``-th block (1-based), or on finish."""

    def __init__(self, tag: str | None = None, fire_on: int | None = None, tail: str | None = None):
        self.tag, self.fire_on, self.tail = tag, fire_on, tail
        self.begun = 0
        self.blocks = 0
        self.finished = 0

    def begin(self) -> None:
        self.begun += 1
        self.blocks = 0

    def accept(self, block):
        self.blocks += 1
        return self.tag if self.fire_on == self.blocks else None

    def finish(self):
        self.finished += 1
        return self.tail


class _Time:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _recognizer(engine, **kw):
    t = _Time()
    r = kws.KeywordSpotterRecognizer(engine, clock=t.clock, sleep=t.sleep, **kw)
    return r, t


def test_the_keyword_list_is_the_closed_command_list_and_nothing_else():
    assert kws.KEYWORD_PHRASES == tuple(phrases[0] for phrases in COMMAND_PHRASES.values())
    assert len(kws.KEYWORD_PHRASES) == len(LocalCommand) == 6
    for phrase in kws.KEYWORD_PHRASES:
        assert route_phrase(phrase) is not None


def test_the_committed_keywords_file_names_exactly_those_phrases():
    tags = [line.rsplit("@", 1)[1].strip() for line in kws.keywords_text().splitlines() if line]
    assert [t.replace("_", " ") for t in tags] == list(kws.KEYWORD_PHRASES)


def test_a_hit_returns_the_phrase_the_router_names():
    for tag, command in [
        ("stop", LocalCommand.STOP),
        ("quieter", LocalCommand.QUIETER),
        ("louder", LocalCommand.LOUDER),
        ("timer", LocalCommand.TIMER),
        ("what_time_is_it", LocalCommand.TIME),
        ("are_you_connected", LocalCommand.CONNECTED),
    ]:
        r, _ = _recognizer(_Engine(tag, fire_on=3))
        heard = r.listen(_Capture(100), threading.Event())
        assert route_phrase(heard) is command, tag


def test_a_hit_stops_listening_at_once():
    engine = _Engine("stop", fire_on=3)
    capture = _Capture(100, per_call=2)
    r, _ = _recognizer(engine)
    assert r.listen(capture, threading.Event()) == "stop"
    assert engine.blocks == 3  # the 4th block of poll 2 is not fed
    assert capture.polls == 2  # no further poll once it hit


def test_a_tag_off_the_list_is_dropped_not_returned():
    r, _ = _recognizer(_Engine("play_music", fire_on=2))
    assert r.listen(_Capture(10), threading.Event()) is None


def test_silence_returns_none_after_the_window_of_audio_and_flushes_the_tail():
    engine = _Engine()
    r, _ = _recognizer(engine, window_s=1.0)
    budget = int(1.0 / BLOCK_DURATION_S) + 1
    assert r.listen(_Capture(10_000), threading.Event()) is None
    assert engine.blocks == budget
    assert engine.finished == 1


def test_a_keyword_that_ends_with_the_window_is_found_by_the_flush():
    r, _ = _recognizer(_Engine(tail="louder"), window_s=0.5)
    assert r.listen(_Capture(10_000), threading.Event()) == "louder"


def test_a_dry_stream_gives_up_on_the_wall_clock_not_forever():
    engine = _Engine()
    r, t = _recognizer(engine, window_s=1.0)
    assert r.listen(_Capture(0), threading.Event()) is None
    assert t.now >= 1.0 and t.sleeps  # it waited, politely, and then stopped


def test_each_listen_starts_a_fresh_stream():
    engine = _Engine("stop", fire_on=1)
    r, _ = _recognizer(engine)
    r.listen(_Capture(5), threading.Event())
    r.listen(_Capture(5), threading.Event())
    assert engine.begun == 2


def test_stop_event_ends_the_listen_with_nothing():
    engine = _Engine("stop", fire_on=5)
    stop = threading.Event()
    stop.set()
    r, _ = _recognizer(engine)
    assert r.listen(_Capture(100), stop) is None
    assert engine.blocks == 0


def test_an_engine_error_propagates_for_the_funnel_to_log():
    class Boom(_Engine):
        def accept(self, block):
            raise RuntimeError("model")

    r, _ = _recognizer(Boom())
    with pytest.raises(RuntimeError):
        r.listen(_Capture(5), threading.Event())
