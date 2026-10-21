"""A spoken "stop" while listening ends the turn on the robot (owner request 2026-10-21)."""

from __future__ import annotations

import asyncio

import pytest

from maipai_body.bodies.stackchan.stop_phrases import is_stop_phrase


@pytest.mark.parametrize(
    "text",
    [
        "stop",
        "Stop.",
        "StackChan, stop",
        "stack chan stop please",
        "be quiet",
        "quiet",
        "never mind",
        "Cancel",
        "that's enough",
        "stop talking",
        "stop listening",
        "Okay, stop!",
    ],
)
def test_stop_phrases_are_recognised(text):
    assert is_stop_phrase(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "stop the music in the kitchen",
        "what is the bus stop",
        "can you be quiet during the movie tonight",
        "cancel my dentist appointment",
        "turn the volume up",
    ],
)
def test_other_sentences_still_go_to_the_hub(text):
    assert not is_stop_phrase(text)


def test_the_bridge_goes_idle_on_a_stop_phrase_without_asking_the_hub(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module
    from maipai_body.speech.stt_stream import SttStreamResult
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

    class StopStt:
        def __init__(self, base, cookie):
            pass

        def run(self, capture, **kwargs):
            return SttStreamResult(kind="final", text="StackChan, stop")

    idle_for: list[str] = []

    async def send_idle(device_id):
        idle_for.append(device_id)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    server.send_idle = send_idle
    FakeTurn.streams = []
    FakeTts.sentences = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    heard: list[str] = []
    bridge = turn_module.StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=StopStt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
        on_user_words=heard.append,
    )
    loop.run_until_complete(bridge._run("session", "device", FakeCapture()))
    loop.close()
    assert idle_for == ["device"]
    assert FakeTurn.streams == [] and FakeTts.sentences == []
    assert heard == []  # a stop is not "kind words"
