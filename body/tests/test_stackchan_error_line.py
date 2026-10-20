"""The apology line can never loop (owner request 2026-10-20)."""

from __future__ import annotations

import asyncio
import logging

from maipai_body.bodies.stackchan.error_line import ErrorLineBreaker
from maipai_body.speech.stt_stream import SttStreamResult


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_apology_is_spoken_once_then_never_twice_in_a_row():
    clock = _Clock()
    breaker = ErrorLineBreaker(clock=clock)
    assert breaker.allow() is True
    clock.now += 10
    assert breaker.allow() is False  # the last thing said was the same line
    assert breaker.suppressed == 1


def test_the_cooldown_lasts_sixty_seconds_after_other_speech_intervenes():
    clock = _Clock()
    breaker = ErrorLineBreaker(clock=clock)
    assert breaker.allow() is True
    clock.now += 10
    breaker.note_speech()  # a reply played in between: not "twice in a row" any more
    clock.now += 10
    assert breaker.allow() is False  # still inside the 60 s cooldown
    clock.now += 61
    assert breaker.allow() is True


def test_never_within_three_seconds_of_any_speech_output():
    clock = _Clock()
    breaker = ErrorLineBreaker(clock=clock)
    breaker.note_speech()
    clock.now += 2
    assert breaker.allow() is False
    clock.now += 2
    assert breaker.allow() is True


def test_the_circuit_breaker_silences_it_until_a_real_transcript(caplog):
    clock = _Clock()
    breaker = ErrorLineBreaker(clock=clock)
    with caplog.at_level(logging.INFO, logger="maipai_body.bodies.stackchan.error_line"):
        results = []
        for _ in range(6):  # six requests, 20 s apart: well inside two minutes
            results.append(breaker.allow())
            clock.now += 20
    assert results == [True, False, False, False, False, False]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "suppressed" in warnings[0].getMessage()
    assert any("error line suppressed (" in r.getMessage() for r in caplog.records)
    clock.now += 200  # even long after the cooldown, the open breaker stays silent
    assert breaker.allow() is False
    breaker.note_real_final()  # the person spoke: the breaker resets
    clock.now += 61
    assert breaker.allow() is True


def test_the_cooldown_expires_after_sixty_seconds():
    clock = _Clock()
    breaker = ErrorLineBreaker(clock=clock)
    assert breaker.allow() is True
    breaker.note_speech()
    clock.now += 59
    assert breaker.allow() is False
    clock.now += 62
    assert breaker.allow() is True


def test_five_silent_follow_ups_say_nothing_and_leave_the_device_idle(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module
    from tests.test_stackchan_turn import (  # type: ignore[import-not-found]
        FakeCapture,
        FakePlayback,
        FakeServer,
        FakeTts,
        InlineExecutor,
        Link,
        Offline,
    )

    class SilentStt:
        def __init__(self, base, cookie):
            pass

        def run(self, capture, **kwargs):
            return SttStreamResult(kind="timeout")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    FakeTts.sentences = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    bridge = turn_module.StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=SilentStt,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
    )
    for index in range(5):
        loop.run_until_complete(bridge._run(f"s{index}", "device", FakeCapture()))
    loop.close()
    assert FakeTts.sentences == []  # not one spoken line
    assert server.idles == ["device"] * 5  # and it waits for the wake word
    assert bridge._quiet_streak == 5


def test_repeated_hub_failures_after_speech_say_at_most_one_line_then_a_real_phrase_resets(
    monkeypatch,
):
    import maipai_body.bodies.stackchan.turn as turn_module
    from tests.test_stackchan_turn import (  # type: ignore[import-not-found]
        FakeCapture,
        FakePlayback,
        FakeServer,
        FakeTts,
        FakeTurn,
        InlineExecutor,
        Link,
        Offline,
    )

    now = [1000.0]
    results = [SttStreamResult(kind="error", speech_s=2.0)] * 4 + [
        SttStreamResult(kind="final", text="hello"),
        SttStreamResult(kind="error", speech_s=2.0),
    ]

    class ScriptedStt:
        def __init__(self, base, cookie):
            pass

        def run(self, capture, **kwargs):
            return results.pop(0)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    FakeTts.sentences = []
    FakeTurn.streams = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    bridge = turn_module.StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=ScriptedStt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
        clock=lambda: now[0],
    )
    apology = "I couldn't understand that. Please try again."
    for index in range(4):
        loop.run_until_complete(bridge._run(f"s{index}", "device", FakeCapture()))
        now[0] += 5
    assert FakeTts.sentences.count(apology) == 1  # four failures, one spoken line
    loop.run_until_complete(bridge._run("real", "device", FakeCapture()))  # a real phrase
    now[0] += 70
    loop.run_until_complete(bridge._run("after", "device", FakeCapture()))
    loop.close()
    assert FakeTts.sentences.count(apology) == 2  # the breaker reset and the cooldown passed
