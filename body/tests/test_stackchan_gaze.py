"""Honest answers to "what are you looking at?", from why the head last moved."""

from __future__ import annotations

import random

import pytest

from maipai_body.app import StackChanBehavior
from maipai_body.bodies.stackchan import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.gaze import ANSWERS, GazeReason, GazeState, is_gaze_question

QUESTIONS = [
    "What are you looking at?",
    "what are you looking for",
    "why are you looking over there",
    "where are you looking",
    "what are you staring at",
    "who are you looking at",
]


@pytest.mark.parametrize("text", QUESTIONS)
def test_gaze_questions_are_recognised(text):
    assert is_gaze_question(text)


@pytest.mark.parametrize(
    "text",
    [
        "what do you see",
        "tell me what you are looking at in this picture",
        "what is the weather",
        "",
    ],
)
def test_vision_and_other_questions_are_left_to_the_hub(text):
    assert not is_gaze_question(text)
    assert GazeState().answer(text) is None


def _state(now, *, asleep=False, wandering=False):
    return GazeState(
        clock=lambda: now[0],
        asleep=lambda: asleep,
        wandering=lambda: wandering,
        rng=random.Random(2),
    )


def test_following_a_face_says_so_and_claims_nothing_more():
    now = [100.0]
    gaze = _state(now)
    gaze.note(GazeReason.TRACK)
    line = gaze.answer("what are you looking at")
    assert line in ANSWERS[GazeReason.TRACK]
    assert "see" not in line.lower().replace("you're good company", "")


def test_a_spoken_command_is_named_for_a_minute_and_then_forgotten():
    now = [100.0]
    gaze = _state(now)
    gaze.note(GazeReason.COMMAND, "left")
    assert gaze.answer("why are you looking over there") == "You asked me to look left!"
    gaze.note(GazeReason.COMMAND, "around")
    assert gaze.answer("what are you looking at") == "You asked me to look around!"
    now[0] += 61
    assert gaze.answer("what are you looking at") in ANSWERS[GazeReason.IDLE]


def test_a_lost_face_is_a_search_for_twenty_seconds():
    now = [100.0]
    gaze = _state(now)
    gaze.note(GazeReason.SEARCH)
    assert gaze.answer("what are you looking for") in ANSWERS[GazeReason.SEARCH]
    now[0] += 21
    assert gaze.answer("what are you looking for") in ANSWERS[GazeReason.IDLE]


def test_thinking_and_idle_wandering_both_say_looking_around():
    now = [100.0]
    gaze = _state(now)
    gaze.note(GazeReason.THINKING)
    assert gaze.answer("what are you looking at") in ANSWERS[GazeReason.THINKING]
    wandering = _state(now, wandering=True)
    assert wandering.answer("what are you looking at") in ANSWERS[GazeReason.SWEEP]


def test_level_and_nothing_is_nothing_in_particular():
    assert _state([0.0]).answer("what are you looking at") in ANSWERS[GazeReason.IDLE]


def test_asleep_or_night_is_resting_whatever_the_last_move_was():
    now = [100.0]
    gaze = _state(now, asleep=True)
    gaze.note(GazeReason.TRACK)
    assert gaze.answer("what are you looking at") in ANSWERS[GazeReason.REST]


def test_the_same_answer_is_not_given_twice_in_a_row():
    gaze = _state([100.0])
    lines = [gaze.answer("what are you looking at") for _ in range(8)]
    assert all(a != b for a, b in zip(lines, lines[1:], strict=False))


def test_no_answer_uses_surveillance_wording_or_names_what_it_did_not_detect():
    banned = ("watching you", "monitor", "record", "camera", "i saw", "i can see", "spying")
    for lines in ANSWERS.values():
        for line in lines:
            assert not any(word in line.lower() for word in banned), line


def test_the_behavior_notes_thinking_and_tracking_and_losing_a_face():
    from types import SimpleNamespace

    class Vision:
        def __init__(self):
            self.detected = True

        def track_stream_frame(self, *, deadline_s=0.4, may_move=None):
            if may_move is not None:
                may_move()
            return SimpleNamespace(detected=self.detected, x=0.5, y=0.5)

    vision = Vision()
    behavior = StackChanBehavior(
        StackChanRobotAdapter(FakeStackChanDeviceClient()).robot, vision_bridge=vision
    )
    try:
        behavior.idle_still = lambda: False
        behavior.render_turn_state("thinking")
        assert behavior.gaze.reason is GazeReason.THINKING
        behavior._active.clear()
        behavior.watch_for_faces(10.0)
        assert behavior.gaze.reason is GazeReason.TRACK
        vision.detected = False
        for t in (11.0, 11.6, 12.2, 12.8):
            behavior.watch_for_faces(t)
        assert behavior.gaze.reason is GazeReason.SEARCH
    finally:
        behavior.close()


def test_the_bridge_answers_a_gaze_question_without_asking_the_hub(monkeypatch):
    import asyncio

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

    class Stt:
        def __init__(self, base, cookie):
            pass

        def run(self, capture, **kwargs):
            return SttStreamResult(kind="final", text="What are you looking at?")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    FakeTurn.streams = []
    FakeTts.sentences = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    gaze = _state([100.0])
    gaze.note(GazeReason.COMMAND, "left")
    bridge = turn_module.StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=Stt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
        gaze_control=gaze,
    )
    loop.run_until_complete(bridge._run("session", "device", FakeCapture()))
    loop.close()
    assert FakeTurn.streams == []
    assert FakeTts.sentences == ["You asked me to look left!"]
