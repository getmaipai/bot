"""Honest answers to "can you see me?" and the picture questions."""

from __future__ import annotations

import random

import pytest

from maipai_body.bodies.stackchan.sight import (
    CAMERA_OFF,
    NOBODY,
    NOT_READY,
    PICTURES_LATER,
    YES,
    SightAnswers,
)


def _answers(*, age=None, camera=True, ready=True):
    return SightAnswers(
        face_age=lambda: age,
        camera_on=lambda: camera,
        detector_ready=lambda: ready,
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
    assert _answers(age=60.0).answer("can you see me") in NOBODY
    assert _answers(age=None).answer("can you see me") in NOBODY


def test_with_the_camera_off_it_says_so_plainly():
    assert _answers(age=1.0, camera=False).answer("can you see me") in CAMERA_OFF


def test_when_face_finding_is_not_ready_it_says_that_not_nobody():
    assert _answers(age=None, ready=False).answer("can you see me") in NOT_READY


def test_it_never_answers_with_a_flat_i_cannot_see():
    lines = YES + NOBODY + CAMERA_OFF + NOT_READY + PICTURES_LATER
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
    assert _answers(age=1.0).answer(text) in PICTURES_LATER


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
    answers = _answers(age=None, ready=True)
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
    assert answers.answer("are the lights on") in NOT_READY
