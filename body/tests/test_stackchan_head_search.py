"""Looking around: for a face when the picture moves without one, and before concluding dark."""

from __future__ import annotations

import logging
import math
from types import SimpleNamespace

from maipai_body.app import StackChanBehavior
from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.head_search import (
    COOLDOWN_S,
    DARK_STEPS,
    PERSON_STEPS,
    STEP_S,
    HeadSearch,
)
from maipai_body.bodies.stackchan.profile import CENTRE_PITCH_DEG


def test_a_search_runs_its_poses_in_turn_then_finishes_and_cools_down():
    search = HeadSearch(clock=lambda: 0.0)
    assert search.start("person", PERSON_STEPS, 10.0)
    assert search.active and not search.start("dark", DARK_STEPS, 10.0)  # one at a time
    assert search.due(10.0) == PERSON_STEPS[0]
    assert search.due(10.1) is None  # the pose is held for STEP_S
    assert search.due(10.0 + STEP_S) == PERSON_STEPS[1]
    assert search.due(10.0 + 2 * STEP_S) == PERSON_STEPS[2]
    assert search.due(10.0 + 3 * STEP_S) == PERSON_STEPS[3]
    assert not search.finished(10.0 + 3 * STEP_S)
    assert search.finished(10.0 + 4 * STEP_S)
    assert search.stop(14.0) == "person"
    assert not search.active
    assert not search.may_start("person", 14.0 + COOLDOWN_S["person"] - 1)
    assert search.may_start("person", 14.0 + COOLDOWN_S["person"])
    assert search.may_start("dark", 14.0)  # another reason has its own cooldown


class _Vision:
    """A bridge whose picture moves, with or without a face, flat or lit."""

    def __init__(self, *, detected=False, motion_age=1.0, luma=120.0):
        self.detected = detected
        self.motion = motion_age
        self.luma = luma
        self.last_motion = 0.3 if motion_age is not None else 0.0

    def track_stream_frame(self, *, deadline_s=0.4, may_move=None):
        if may_move is not None:
            may_move()
        return SimpleNamespace(detected=self.detected, x=0.5, y=0.3)

    def motion_age(self):
        return self.motion

    def latest_look(self, *, max_age_s, take=False):
        return (b"\xff\xd8", 1 if self.detected else 0, self.luma, None)


def _behavior(vision):
    device = FakeStackChanDeviceClient()
    behavior = StackChanBehavior(StackChanRobotAdapter(device).robot, vision_bridge=vision)
    behavior.idle_level = "normal"
    behavior.idle_still = lambda: False
    behavior.watch_level = lambda: "presence"
    behavior.night_active = lambda: False
    return behavior, device


def _head_calls(device):
    return [c.arguments for c in device.calls if c.name == "self.robot.set_head_angles"]


def test_movement_without_a_face_makes_the_head_look_up_and_over_then_centre(caplog):
    vision = _Vision(detected=False, motion_age=1.0)
    behavior, device = _behavior(vision)
    try:
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            behavior.search_tick(100.0)
            assert behavior._search.reason == "person"
            before = len(_head_calls(device))
            behavior.search_tick(100.0)  # the first pose is due at once
            calls = _head_calls(device)
            assert len(calls) == before + 1
            assert calls[-1]["pitch"] == round(CENTRE_PITCH_DEG + 20) and calls[-1]["yaw"] == 0
            behavior.search_tick(100.0 + STEP_S)
            assert _head_calls(device)[-1]["yaw"] == -25
            behavior.search_tick(100.0 + 2 * STEP_S)
            assert _head_calls(device)[-1]["yaw"] == 25
            behavior.search_tick(100.0 + 3 * STEP_S)
            behavior.search_tick(100.0 + 4 * STEP_S)  # over: back to centre
            assert not behavior._search.active
            assert _head_calls(device)[-1] == {
                "yaw": 0,
                "pitch": round(CENTRE_PITCH_DEG),
                "speed": _head_calls(device)[-1]["speed"],
            }
        lines = [r.getMessage() for r in caplog.records]
        assert any("looking for a face" in line for line in lines)
        assert any("looking around (person): yaw -25, pitch 20" in line for line in lines)
        assert any("stopped looking for a face: done" in line for line in lines)
        # Not again inside the cooldown, even though the picture still moves.
        behavior.search_tick(110.0)
        assert not behavior._search.active
    finally:
        behavior.close()


def test_the_search_stops_the_moment_a_face_is_seen():
    vision = _Vision(detected=False, motion_age=1.0)
    behavior, device = _behavior(vision)
    try:
        behavior.search_tick(100.0)
        behavior.search_tick(100.0)
        assert behavior._search.active
        vision.detected = True
        behavior.watch_for_faces(100.5)  # the face watcher sees it
        behavior.search_tick(100.5)
        assert not behavior._search.active
        assert _head_calls(device)[-1]["yaw"] == 0  # back to centre; following takes over
    finally:
        behavior.close()


def test_no_search_when_nobody_seems_there_while_resting_or_during_a_turn():
    vision = _Vision(detected=False, motion_age=None)
    behavior, _device = _behavior(vision)
    try:
        behavior.search_tick(100.0)
        assert not behavior._search.active  # nothing moved: nobody seems to be there
        vision.motion = 1.0
        behavior._active.set()  # a turn
        behavior.search_tick(100.0)
        assert not behavior._search.active
        behavior._active.clear()
        rest = behavior._rest
        behavior._rest = SimpleNamespace(stage="asleep")
        behavior.search_tick(100.0)
        assert not behavior._search.active
        behavior._rest = rest
        behavior.search_tick(100.0)
        assert behavior._search.active
        behavior._active.set()  # a turn starts mid-search: it ends at once
        behavior.search_tick(100.2)
        assert not behavior._search.active
    finally:
        behavior.close()


def test_a_refused_head_gate_ends_the_search_without_moving():
    vision = _Vision(detected=False, motion_age=1.0)
    behavior, device = _behavior(vision)
    try:
        behavior.head_gate.allow = lambda source, **kw: bool(kw.get("essential"))
        behavior.search_tick(100.0)
        before = len(_head_calls(device))
        behavior.search_tick(100.0)
        assert not behavior._search.active
        assert len(_head_calls(device)) == before + 1  # only the essential return to centre
    finally:
        behavior.close()


def test_a_flat_dark_picture_is_checked_by_looking_around_before_it_counts_as_dark(caplog):
    vision = _Vision(detected=False, motion_age=None, luma=None)
    behavior, device = _behavior(vision)
    behavior.lux = lambda: 6.4  # the sensor at its floor
    try:
        assert behavior.light_now(None, flat=True, now=100.0) is None  # not concluded yet
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            behavior.search_tick(100.0)
            assert behavior._search.reason == "dark"
            for i in range(4):
                behavior.search_tick(100.0 + i * STEP_S)
            assert not behavior._search.active
        yaws = [c["yaw"] for c in _head_calls(device)[-4:]]
        assert yaws == [-25, 25, 0, 0]
        assert behavior.light_now(None, flat=True, now=104.0) == "dark"
        assert behavior.light_for_sight(now=104.0) == "dark"
        assert any("dark confirmed" in r.getMessage() for r in caplog.records)
    finally:
        behavior.close()


def test_detail_seen_while_looking_around_means_not_dark(caplog):
    vision = _Vision(detected=False, motion_age=None, luma=None)
    behavior, _device = _behavior(vision)
    behavior.lux = lambda: 6.4
    try:
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            behavior.search_tick(100.0)
            behavior.search_tick(100.0)
            vision.luma = 150.0  # the wall to the left is lit after all
            behavior.search_tick(100.0 + STEP_S)
            vision.luma = None
            for i in range(2, 5):
                behavior.search_tick(100.0 + i * STEP_S)
            assert not behavior._search.active
        assert behavior.light_now(None, flat=True, now=104.0) is None  # unknown, not dark
        assert any("not dark" in r.getMessage() for r in caplog.records)
    finally:
        behavior.close()


def test_when_the_head_may_not_move_the_sensor_alone_decides_dark():
    vision = _Vision(detected=False, motion_age=None, luma=None)
    behavior, _device = _behavior(vision)
    behavior.lux = lambda: 6.4
    try:
        behavior.idle_still = lambda: True  # charging or level still: no looking around
        behavior.search_tick(100.0)
        assert not behavior._search.active
        assert behavior.light_now(None, flat=True, now=100.0) == "dark"
    finally:
        behavior.close()


def test_search_poses_are_within_the_follow_span():
    for step in PERSON_STEPS + DARK_STEPS:
        assert abs(step.yaw_deg) <= 30 and 0 <= step.pitch_deg <= 20
        assert math.radians(CENTRE_PITCH_DEG + step.pitch_deg) < math.radians(85)
