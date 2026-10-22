"""Honest answers to "can you see me?" and the picture questions."""

from __future__ import annotations

import random

import pytest

from maipai_body.bodies.stackchan.sight import (
    CAMERA_OFF,
    NOT_READY,
    YES,
    SightAnswers,
)


def _answers(*, age=None, camera=True, running=120.0, light=None):
    return SightAnswers(
        face_age=lambda: age,
        camera_on=lambda: camera,
        light=lambda: light,
        camera_running_s=lambda: running,
        rng=random.Random(1),
    )


@pytest.mark.parametrize(
    "text",
    [
        "Can you see me?",
        "can you see me right now",
        "do you see me",
        "are you able to see me",
        "can you spot me",
    ],
)
def test_with_a_face_seen_a_moment_ago_it_says_yes(text):
    assert _answers(age=2.0).answer(text) in YES


def test_a_face_seen_long_ago_is_not_claimed():
    assert _answers(age=60.0).answer("can you see me").startswith("I can't spot anyone right now")
    assert _answers(age=None).answer("can you see me").startswith("I can't spot anyone right now")


def test_with_the_camera_off_it_says_so_plainly():
    assert _answers(age=1.0, camera=False).answer("can you see me") in CAMERA_OFF


def test_when_face_finding_is_not_ready_it_says_that_not_nobody():
    assert _answers(age=None, running=5.0).answer("can you see me") in NOT_READY
    assert _answers(age=None, running=None).answer("can you see me") in NOT_READY


def test_it_never_answers_with_a_flat_i_cannot_see():
    lines = YES + CAMERA_OFF + NOT_READY
    assert not any(line.lower().startswith(("no, i can't see", "i can't see")) for line in lines)


@pytest.mark.parametrize(
    "text",
    [
        "what do you see",
        "What am I holding?",
        "look at this",
        "what's this",
        "what is this",
        "what is that",
        "what can you see",
    ],
)
def test_picture_questions_get_the_interim_line_not_the_hub(text):
    assert _answers(age=1.0).answer(text).startswith("My camera is on")


@pytest.mark.parametrize(
    "text",
    [
        "what is the weather",
        "can you see the weather forecast",
        "tell me what this song is",
        "",
        None,
    ],
)
def test_other_speech_is_not_a_sight_question(text):
    assert _answers().answer(text) is None


def test_the_same_line_is_not_repeated_back_to_back():
    answers = _answers(age=1.0)
    lines = [answers.answer("can you see me") for _ in range(6)]
    assert all(a != b for a, b in zip(lines, lines[1:], strict=False))


def test_light_and_looking_questions_have_their_own_kind():
    answers = _answers(age=None)
    assert answers.kind("is the light on") == "light"
    assert answers.kind("are the lights off in here") == "light"
    assert answers.kind("is it dark in here") == "light"
    assert answers.kind("what are you looking at") == "picture"
    assert answers.kind("can you see me") == "see_me"
    assert answers.kind("what time is it") is None


def test_the_host_answer_for_the_light_comes_from_the_brightness():
    answers = SightAnswers(
        face_age=lambda: None,
        camera_on=lambda: True,
        light=lambda: "dark",
        rng=random.Random(1),
    )
    assert "dark" in answers.answer("is the light on")
    answers = SightAnswers(face_age=lambda: None, camera_on=lambda: True, light=lambda: "bright")
    assert "bright" in answers.answer("are the lights on")
    answers = SightAnswers(face_age=lambda: None, camera_on=lambda: True)
    assert "can't tell how bright" in answers.answer("are the lights on")


def test_a_camera_that_has_run_a_while_says_plainly_what_it_can_and_cannot_do():
    answer = _answers(age=None, running=300.0, light="dim").answer("can you see me")
    assert "camera is on" in answer and "the room looks dim" in answer
    assert "can't describe" in answer and "ask me again" not in answer.lower()
    picture = _answers(running=300.0, light="bright").answer("what do you see")
    assert (
        picture
        == "My camera is on and the room looks bright, but I can't describe what's in it yet."
    )
    assert "can't describe what's in the room" in _answers(running=300.0).answer("what do you see")


def test_a_camera_that_has_just_started_says_it_is_starting_and_a_face_still_wins():
    answers = _answers(age=None, running=10.0, light="dim")
    assert answers.answer("what do you see") in NOT_READY
    assert answers.answer("can you see me") in NOT_READY
    assert _answers(age=1.0, running=10.0).answer("can you see me") in YES


def test_the_light_answer_waits_for_the_camera_then_uses_the_brightness():
    assert _answers(running=3.0, light="dark").answer("is the light on") in NOT_READY
    assert "dark" in _answers(running=100.0, light="dark").answer("is the light on")
    assert "can't tell how bright" in _answers(running=100.0).answer("is the light on")
