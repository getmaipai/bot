"""Looking around: for a face when the picture suggests a person, after someone spoke, and
before concluding dark (owner requests 2026-11-12, "natural, not annoying")."""

from __future__ import annotations

import logging
import math
from types import SimpleNamespace

import numpy as np

from maipai_body.app import StackChanBehavior
from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.head_search import (
    DARK_COOLDOWN_S,
    DARK_STEPS,
    GLANCE_PITCH_DEG,
    LOOK_PITCH_DEG,
    MOVE_SPEED,
    PAN_DEG,
    PERSON_BACKOFF_S,
    PERSON_STEPS,
    SPEAKER_COOLDOWN_S,
    STEP_S,
    HeadSearch,
)
from maipai_body.bodies.stackchan.presence_watch import PERSON_SHARE, SceneBaseline
from maipai_body.bodies.stackchan.profile import CENTRE_PITCH_DEG


def test_a_look_runs_its_poses_in_turn_then_finishes():
    search = HeadSearch(clock=lambda: 0.0)
    assert search.start("person", 10.0)
    assert search.active and not search.start("dark", 10.0)  # one at a time
    assert search.due(10.0) == PERSON_STEPS[0]
    assert search.due(10.1) is None  # the pose is held for STEP_S
    assert search.due(10.0 + STEP_S) == PERSON_STEPS[1]
    assert search.due(10.0 + 2 * STEP_S) == PERSON_STEPS[2]
    assert search.due(10.0 + 3 * STEP_S) == PERSON_STEPS[3]
    assert not search.finished(10.0 + 3 * STEP_S)
    assert search.finished(10.0 + 4 * STEP_S)
    assert search.stop(17.0) == "person"
    assert not search.active


def test_a_failed_look_backs_off_one_three_ten_minutes_and_a_face_resets_it():
    search = HeadSearch(clock=lambda: 0.0)
    assert search.start("person", 0.0)
    search.stop(6.0)  # nobody found
    assert search.wait_s("person") == PERSON_BACKOFF_S[0]
    assert not search.may_start("person", 6.0 + PERSON_BACKOFF_S[0] - 1)
    assert search.start("person", 6.0 + PERSON_BACKOFF_S[0])
    search.stop(72.0)
    assert search.wait_s("person") == PERSON_BACKOFF_S[1]
    assert search.start("person", 72.0 + PERSON_BACKOFF_S[1])
    search.stop(260.0)
    assert search.wait_s("person") == PERSON_BACKOFF_S[2]
    search._last_done.clear()
    assert search.start("person", 1000.0)
    search.stop(1003.0, found=True)
    assert search.wait_s("person") == 0.0  # a face found: look again whenever needed
    assert search.may_start("speaker", 1003.0 + SPEAKER_COOLDOWN_S)
    assert search.wait_s("dark") == DARK_COOLDOWN_S


def test_the_look_glances_up_a_little_first_then_looks_up_and_over():
    assert PERSON_STEPS[0].pitch_deg == GLANCE_PITCH_DEG < LOOK_PITCH_DEG
    assert PERSON_STEPS[0].yaw_deg == 0.0
    assert {step.yaw_deg for step in PERSON_STEPS[2:]} == {-PAN_DEG, PAN_DEG}
    for step in PERSON_STEPS + DARK_STEPS:
        assert abs(step.yaw_deg) <= 30 and 0 <= step.pitch_deg <= 25
        assert math.radians(CENTRE_PITCH_DEG + step.pitch_deg) < math.radians(85)


class _Vision:
    """A bridge whose picture moves or not, with or without a face, flat or lit."""

    def __init__(self, *, detected=False, motion_age=None, luma=120.0, thumb=None):
        self.detected = detected
        self.motion = motion_age
        self.luma = luma
        self.thumb = thumb
        self.last_motion = 0.3 if motion_age is not None else 0.0

    def track_stream_frame(self, *, deadline_s=0.4, may_move=None):
        if may_move is not None:
            may_move()
        return SimpleNamespace(detected=self.detected, x=0.5, y=0.3)

    def motion_age(self):
        return self.motion

    def latest_look(self, *, max_age_s, take=False):
        return (b"\xff\xd8", 1 if self.detected else 0, self.luma, self.thumb)


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


def _run_person_look(behavior, device, start):
    behavior.search_tick(start)
    assert behavior._search.reason == "person"
    behavior.search_tick(start)
    for i in range(1, 5):
        behavior.search_tick(start + i * STEP_S)
    assert not behavior._search.active
    return _head_calls(device)


def test_a_picture_that_differs_from_the_empty_room_starts_the_look_without_any_movement(caplog):
    room = np.full((12, 16), 120.0, dtype=np.float32)
    body = room.copy()
    body[:, :10] = 40.0  # a torso over most of the picture, perfectly still
    vision = _Vision(detected=False, motion_age=None, thumb=room)
    behavior, device = _behavior(vision)
    try:
        behavior._baseline.learn(room, 0.0)  # the empty room, learned earlier
        vision.thumb = body
        behavior.watch_for_faces(100.0)  # measures how the picture differs from the room
        assert behavior._person_share >= PERSON_SHARE
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            calls = _run_person_look(behavior, device, 100.2)
        looked = calls[-5:]
        assert looked[0] == {
            "yaw": 0,
            "pitch": round(CENTRE_PITCH_DEG + GLANCE_PITCH_DEG),
            "speed": MOVE_SPEED,
        }
        assert [c["yaw"] for c in looked[1:]] == [0, -PAN_DEG, PAN_DEG, 0]
        assert looked[-1]["pitch"] == round(CENTRE_PITCH_DEG)  # back to rest, slowly
        assert all(c["speed"] == MOVE_SPEED for c in looked)
        lines = [r.getMessage() for r in caplog.records]
        assert any("differs from the empty room" in line for line in lines)
        assert any("looking around (person): yaw -25, pitch 22" in line for line in lines)
        assert any("next look waits 60 s" in line for line in lines)
        behavior.search_tick(110.0)  # not again inside the back-off
        assert not behavior._search.active
    finally:
        behavior.close()


def test_the_empty_room_is_learned_only_while_nobody_seems_to_be_there():
    room = np.full((12, 16), 120.0, dtype=np.float32)
    vision = _Vision(detected=False, motion_age=None, thumb=room)
    behavior, _device = _behavior(vision)
    try:
        behavior.watch_for_faces(100.0)
        assert behavior._baseline.known  # the first picture starts the room
        behavior._last_person_seen = 500.0  # someone was just here
        body = room.copy()
        body[:, :8] = 40.0
        vision.thumb = body
        behavior.watch_for_faces(530.0)
        assert behavior._person_share >= PERSON_SHARE  # the room did not absorb the person
        baseline = SceneBaseline()
        assert baseline.differs(room) == 0.0  # nothing learned yet: nothing is person-like
        baseline.learn(room, 0.0)
        shifted = room + 40.0  # the lights changed: the whole picture is brighter
        assert baseline.differs(shifted) == 0.0
    finally:
        behavior.close()


def test_the_look_stops_the_moment_a_face_is_seen_and_following_takes_over():
    vision = _Vision(detected=False, motion_age=1.0)
    behavior, device = _behavior(vision)
    try:
        behavior.search_tick(100.0)
        behavior.search_tick(100.0)
        assert behavior._search.active
        moves = len(_head_calls(device))
        vision.detected = True
        behavior.watch_for_faces(100.5)  # the face watcher sees it
        behavior.search_tick(100.5)
        assert not behavior._search.active
        # No slow return to rest: following takes over from where the face is.
        assert all(c["speed"] != MOVE_SPEED for c in _head_calls(device)[moves:])
        assert behavior._search.wait_s("person") == 0.0
    finally:
        behavior.close()


def test_a_touch_stops_the_look():
    vision = _Vision(detected=False, motion_age=1.0)
    behavior, device = _behavior(vision)
    try:
        behavior.search_tick(100.0)
        assert behavior._search.active
        touch = SimpleNamespace(kind="head_touch", extra={"strong": 1})
        behavior.event_poll = lambda: [touch, touch]
        behavior.wake_on_touch(100.3)
        assert not behavior._search.active
    finally:
        behavior.close()


def test_no_look_while_resting_at_night_or_mid_reply_and_a_reply_ends_one():
    vision = _Vision(detected=False, motion_age=1.0)
    behavior, _device = _behavior(vision)
    try:
        rest = behavior._rest
        behavior._rest = SimpleNamespace(stage="asleep")
        behavior.search_tick(100.0)
        assert not behavior._search.active
        behavior._rest = rest
        behavior.night_active = lambda: True
        behavior.search_tick(100.0)
        assert not behavior._search.active
        behavior.night_active = lambda: False
        behavior._active.set()  # a turn
        behavior.search_tick(100.0)
        assert not behavior._search.active
        behavior._active.clear()
        behavior.search_tick(100.0)
        assert behavior._search.active
        behavior._active.set()
        behavior._phase = "busy"  # the reply
        behavior.search_tick(100.2)
        assert not behavior._search.active
    finally:
        behavior.close()


def test_the_look_moves_even_when_idle_wandering_must_stay_still():
    """Owner-approved 2026-11-12: the 2026-10-20 "still" rule no longer holds the look back."""
    vision = _Vision(detected=False, motion_age=1.0)
    behavior, device = _behavior(vision)
    try:
        behavior.idle_still = lambda: True  # charging, or idle level still
        behavior.idle_still_reason = lambda: "charging"
        before = len(_head_calls(device))
        behavior.search_tick(100.0)
        behavior.search_tick(100.0)
        assert behavior._search.active and len(_head_calls(device)) == before + 1
    finally:
        behavior.close()


def test_a_refused_head_gate_ends_the_look_without_moving():
    vision = _Vision(detected=False, motion_age=1.0)
    behavior, device = _behavior(vision)
    try:
        behavior.head_gate.allow = lambda source, **kw: bool(kw.get("essential"))
        behavior.search_tick(100.0)
        before = len(_head_calls(device))
        behavior.search_tick(100.0)
        assert not behavior._search.active
        assert len(_head_calls(device)) == before + 1  # only the essential return to rest
    finally:
        behavior.close()


def test_someone_speaking_gets_a_brisk_glance_up_and_a_look_after_the_reply(caplog):
    vision = _Vision(detected=False, motion_age=None)
    behavior, device = _behavior(vision)
    try:
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            behavior.render_turn_state("listening")
        glances = [c for c in _head_calls(device) if c["speed"] == 130]
        assert glances and glances[-1]["pitch"] == round(CENTRE_PITCH_DEG + 15)
        assert any("glanced up toward the speaker" in r.getMessage() for r in caplog.records)
        behavior.search_tick(100.0)  # mid-turn: no look yet
        assert not behavior._search.active
        behavior.render_turn_state("settle")
        behavior._active.clear()
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            behavior.search_tick(101.0)
        assert behavior._search.reason == "speaker"
        assert any("looking for the person who spoke" in r.getMessage() for r in caplog.records)
    finally:
        behavior.close()


def test_a_recent_face_gets_the_turn_toward_it_instead_of_a_glance():
    vision = _Vision(detected=True, motion_age=None)
    behavior, device = _behavior(vision)
    try:
        import time

        behavior.watch_for_faces(time.monotonic())  # the turn-toward uses the real clock
        behavior.render_turn_state("listening")
        assert behavior._turn_face_held is True
        assert not behavior._search_after_turn
        assert not [c for c in _head_calls(device) if c["speed"] == 130]
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
        assert behavior.light_now(None, flat=True, now=106.0) == "dark"
        assert behavior.light_for_sight(now=106.0) == "dark"
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
        assert behavior.light_now(None, flat=True, now=108.0) is None  # unknown, not dark
        assert any("not dark" in r.getMessage() for r in caplog.records)
    finally:
        behavior.close()


def test_when_the_robot_rests_the_sensor_alone_decides_dark():
    vision = _Vision(detected=False, motion_age=None, luma=None)
    behavior, _device = _behavior(vision)
    behavior.lux = lambda: 6.4
    try:
        behavior._rest = SimpleNamespace(stage="drowsy")
        behavior.search_tick(100.0)
        assert not behavior._search.active
        assert behavior.light_now(None, flat=True, now=100.0) == "dark"
    finally:
        behavior.close()


def test_a_flat_picture_in_a_lit_room_is_person_like(caplog):
    """The owner's hoodie against the lens (2026-11-12): no detail, sensor 10, nothing moving."""
    vision = _Vision(detected=False, motion_age=None, luma=None)
    behavior, _device = _behavior(vision)
    behavior.lux = lambda: 10.0
    try:
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            behavior.search_tick(100.0)
        assert behavior._search.reason == "person"
        assert any("right against the lens" in r.getMessage() for r in caplog.records)
    finally:
        behavior.close()


def test_movement_without_a_face_counts_as_a_person_for_the_rest_policy():
    vision = _Vision(detected=False, motion_age=0.5)
    behavior, _device = _behavior(vision)
    try:
        assert behavior.watch_for_faces(100.0) is False
        assert behavior._last_person_seen == 100.0
        vision.motion = 40.0  # nothing moved for a while
        behavior.watch_for_faces(100.6)
        assert behavior._last_person_seen == 100.0
    finally:
        behavior.close()
