import random

import pytest

from maipai_body.bodies.stackchan.orientation import (
    AXIS_POSES,
    FACE_FOR_POSE,
    FACE_REFRESH_S,
    LINE_GAP_S,
    OrientationReactions,
    pose_for_axis,
)


class Harness:
    def __init__(self, *, say_result=True):
        self.now = 0.0
        self.faces = []
        self.lines = []
        self.rotations = []
        self.holds = []
        self.quiet = False
        self.busy = False
        self.say_result = say_result
        self.reactions = OrientationReactions(
            face=self.faces.append,
            say=self.say,
            rotate=self.rotations.append,
            hold_motion=self.holds.append,
            quiet=lambda: self.quiet,
            busy=lambda: self.busy,
            clock=lambda: self.now,
            rng=random.Random(1),
        )

    def say(self, line):
        self.lines.append(line)
        return self.say_result

    def event(self, axis):
        return self.reactions.on_event({"axis": axis})


@pytest.mark.parametrize("axis,pose", AXIS_POSES.items())
def test_pose_for_axis_and_each_axis_changes_to_pose(axis, pose):
    h = Harness()
    assert pose_for_axis(axis) == pose
    assert h.event(axis) is (pose != "upright")
    assert h.reactions.pose == pose


def test_unknown_axis_and_non_string_axis_are_ignored():
    h = Harness()
    assert pose_for_axis("?axis") is None
    assert pose_for_axis(None) is None
    assert h.event("?axis") is False
    assert h.reactions.on_event({"axis": 1}) is False
    assert h.rotations == h.faces == h.lines == []


def test_same_pose_twice_is_ignored():
    h = Harness()
    assert h.event("+x")
    state = (list(h.rotations), list(h.holds), list(h.faces), list(h.lines))
    assert h.event("+x") is False
    assert (h.rotations, h.holds, h.faces, h.lines) == state


def test_rotation_hold_and_face_follow_pose():
    h = Harness()
    for axis, pose in AXIS_POSES.items():
        if not h.event(axis):
            continue  # already in that pose (the robot starts upright)
        assert h.rotations[-1] == (180 if pose == "upside_down" else 0)
        assert h.holds[-1] is (pose != "upright")
        assert h.faces[-1] == FACE_FOR_POSE[pose]


def test_busy_suppresses_face_and_line():
    h = Harness()
    h.busy = True
    assert h.event("+x")
    assert h.rotations == [0]
    assert h.holds == [True]
    assert h.faces == h.lines == []


def test_quiet_suppresses_line_but_keeps_face_rotation_and_hold():
    h = Harness()
    h.quiet = True
    assert h.event("+x")
    assert h.rotations == [0]
    assert h.holds == [True]
    assert h.faces == ["doubt"]
    assert h.lines == []


def test_line_gap_and_skipped_line_does_not_start_gap():
    h = Harness()
    h.event("+x")
    assert len(h.lines) == 1
    h.now += LINE_GAP_S - 1
    h.event("-x")
    assert len(h.lines) == 1
    h.now += 1
    h.event("+y")
    assert len(h.lines) == 2

    skipped = Harness(say_result=False)
    skipped.event("+x")
    skipped.now += 1
    skipped.event("-x")
    assert len(skipped.lines) == 2


def test_line_is_never_repeated_in_a_row():
    h = Harness()
    previous = None
    axes = list(AXIS_POSES)
    for index in range(50):
        h.now += 200
        axis = axes[index % len(axes)]
        h.event(axis)
        if h.lines:
            assert h.lines[-1] != previous
            previous = h.lines[-1]


def test_tick_refreshes_face_at_interval_and_respects_upright_and_busy():
    h = Harness()
    h.event("+x")
    h.now += FACE_REFRESH_S - 0.01
    h.reactions.tick()
    assert h.faces == ["doubt"]
    h.now += 0.01
    h.reactions.tick()
    assert h.faces == ["doubt", "doubt"]
    h.busy = True
    h.now += FACE_REFRESH_S
    h.reactions.tick()
    assert len(h.faces) == 2
    h.busy = False
    h.event("-y")
    before = len(h.faces)
    h.now += FACE_REFRESH_S
    h.reactions.tick()
    assert len(h.faces) == before


def test_reset_restores_neutral_without_speech_and_rotates_even_when_upright():
    h = Harness()
    h.reactions.reset()
    assert h.rotations == [0]
    assert h.holds == h.faces == h.lines == []
    h.event("+y")
    lines = list(h.lines)
    h.reactions.reset()
    assert h.reactions.pose == "upright"
    assert h.rotations[-1] == 0
    assert h.holds[-1] is False
    assert h.faces[-1] == "neutral"
    assert h.lines == lines
