import random

import pytest

from maipai_body.bodies.stackchan.orientation import (
    AXIS_POSES,
    FACE_FOR_POSE,
    FACE_REFRESH_S,
    LINE_GAP_S,
    POSE_CHANGE_GAP_S,
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


def test_different_pose_has_short_floor_and_same_pose_has_own_two_minute_gap():
    h = Harness()
    h.event("+x")
    assert len(h.lines) == 1
    h.now += POSE_CHANGE_GAP_S - 1
    h.event("-x")
    assert len(h.lines) == 1
    h.now += 1
    h.event("+y")
    assert len(h.lines) == 2
    h.now += POSE_CHANGE_GAP_S
    h.event("+x")  # left_side was said first; it has its own two minute cooldown
    assert len(h.lines) == 2
    h.now += LINE_GAP_S - POSE_CHANGE_GAP_S
    h.event("-y")
    assert len(h.lines) == 3

    skipped = Harness(say_result=False)
    skipped.event("+x")
    skipped.now += 1
    skipped.event("-x")
    assert len(skipped.lines) == 2


def test_a_different_pose_can_speak_after_fifteen_seconds():
    h = Harness()
    h.event("+x")
    h.now += POSE_CHANGE_GAP_S
    h.event("-x")
    assert len(h.lines) == 2


def test_boot_upright_is_silent_but_returning_upright_speaks():
    h = Harness()
    assert h.event("+y") is False
    assert h.lines == []
    h.event("+x")
    h.now += POSE_CHANGE_GAP_S
    h.event("+y")
    assert len(h.lines) == 2
    from maipai_body.bodies.stackchan.orientation import LINE_POOLS

    assert h.lines[-1] in LINE_POOLS["upright"]


def test_reassert_and_turn_end_restore_held_face_without_speech():
    h = Harness()
    h.event("+x")
    lines = list(h.lines)
    h.faces.clear()
    h.reactions.reassert()
    h.reactions.on_turn_end()
    assert h.holds[-1] is True
    assert h.faces == ["doubt", "doubt"]
    assert h.lines == lines


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
    h.event("+y")
    before = len(h.faces)
    h.now += FACE_REFRESH_S
    h.reactions.tick()
    assert len(h.faces) == before


def test_reset_restores_neutral_without_speech_and_rotates_even_when_upright():
    h = Harness()
    h.reactions.reset()
    assert h.rotations == [0]
    assert h.holds == h.faces == h.lines == []
    h.event("-y")
    lines = list(h.lines)
    h.reactions.reset()
    assert h.reactions.pose == "upright"
    assert h.rotations[-1] == 0
    assert h.holds[-1] is False
    assert h.faces[-1] == "neutral"
    assert h.lines == lines


def test_every_pool_is_large_short_and_free_of_em_dashes():
    from maipai_body.bodies.stackchan.orientation import LINE_POOLS, POSES

    assert set(LINE_POOLS) == set(POSES)
    for pose, lines in LINE_POOLS.items():
        assert len(lines) >= 8, pose
        assert len(set(lines)) == len(lines), pose
        for line in lines:
            assert 10 <= len(line) <= 90, line
            assert "—" not in line, line


def test_no_line_repeats_within_the_last_ten_spoken():
    from maipai_body.bodies.stackchan.orientation import RECENT_LINES

    h = Harness()
    spoken = []
    for i in range(120):
        h.now += 200.0
        h.event("+x" if i % 2 == 0 else "+y")  # side, upright, side, upright ...
    spoken = h.lines
    assert len(spoken) == 120
    for i, line in enumerate(spoken):
        assert line not in spoken[max(0, i - RECENT_LINES) : i], (i, line)


def test_the_rotation_is_asked_again_every_minute_while_upside_down():
    from maipai_body.bodies.stackchan.orientation import ROTATION_REFRESH_S

    h = Harness()
    h.event("-y")
    assert h.rotations == [180]
    h.now += ROTATION_REFRESH_S - 1
    h.reactions.tick()
    assert h.rotations == [180]
    h.now += 2
    h.reactions.tick()
    assert h.rotations == [180, 180]
    h.event("+y")  # upright
    h.now += 3 * ROTATION_REFRESH_S
    h.reactions.tick()
    assert h.rotations == [180, 180, 0]


def test_a_unit_standing_normally_is_upright_and_the_opposite_axis_is_upside_down():
    assert pose_for_axis("+y") == "upright"
    assert pose_for_axis("-y") == "upside_down"


def test_the_screen_flip_is_off_until_the_firmware_does_it_safely():
    from maipai_body.bodies.stackchan.orientation import SCREEN_ROTATION_ENABLED

    assert SCREEN_ROTATION_ENABLED is False


def test_face_watching_imports_without_the_reachy_sdk_or_huggingface_hub():
    import subprocess
    import sys

    code = (
        "import sys\n"
        "for m in ('reachy_mini', 'huggingface_hub', 'huggingface_hub.errors', 'cv2'):\n"
        "    sys.modules[m] = None\n"
        "import maipai_body.bodies.stackchan.vision_bridge\n"
        "from maipai_body.vision.yunet import LazyFaceDetector\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_sides_are_named_by_the_robots_own_left_and_right():
    assert pose_for_axis("+x") == "right_side"  # its right ear down, measured 2026-10-22
    assert pose_for_axis("-x") == "left_side"


def test_a_quiet_reason_from_the_caller_is_logged(caplog):
    import logging

    h = Harness()
    h.quiet = "night mode is on"
    with caplog.at_level(logging.INFO, logger="maipai_body.bodies.stackchan.orientation"):
        h.event("+x")
    assert "skipped: night mode is on" in caplog.text
    assert h.lines == []


def test_the_sensors_are_untrusted_while_tilted_and_for_thirty_seconds_after():
    from maipai_body.bodies.stackchan.orientation import SENSOR_SETTLE_S

    h = Harness()
    assert not h.reactions.sensors_untrusted()  # never moved
    h.event("+x")
    assert h.reactions.sensors_untrusted()
    h.now += 100
    h.event("+y")  # upright
    assert h.reactions.sensors_untrusted()
    h.now += SENSOR_SETTLE_S - 1
    assert h.reactions.sensors_untrusted()
    h.now += 2
    assert not h.reactions.sensors_untrusted()
