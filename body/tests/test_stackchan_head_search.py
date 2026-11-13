"""Looking around: for a face when the picture suggests a person, after someone spoke, and
before concluding dark (owner requests 2026-11-12, "natural, not annoying")."""

from __future__ import annotations

import logging
import math
import time
from types import SimpleNamespace

import numpy as np

from maipai_body.app import StackChanBehavior
from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.head_search import (
    ASK_FAST_STEP_S,
    ASK_LEVEL_STEPS,
    ASK_PAN_DEG,
    ASK_SLOW_STEP_S,
    ASK_STEPS,
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
from maipai_body.bodies.stackchan.head_search import (
    STEPS as STEP_TABLE,
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


def test_someone_right_in_front_of_the_lens_gets_the_steep_climb():
    from maipai_body.bodies.stackchan.head_search import CLOSE_PITCHES_DEG, CLOSE_STEPS, STEPS

    assert STEPS["close"] == CLOSE_STEPS
    assert (
        [s.pitch_deg for s in CLOSE_STEPS] == list(CLOSE_PITCHES_DEG) == sorted(CLOSE_PITCHES_DEG)
    )
    assert all(s.yaw_deg == 0.0 for s in CLOSE_STEPS) and CLOSE_PITCHES_DEG[-1] <= 80
    search = HeadSearch(clock=lambda: 0.0)
    assert search.start("close", 0.0)
    search.stop(5.0)  # nobody: the same back-off as the person look
    assert search.wait_s("person") == PERSON_BACKOFF_S[0]


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
        # Started by the picture alone, with nothing moving: the harder back-off (3 minutes).
        assert any("next look waits 180 s" in line for line in lines)
        behavior.search_tick(110.0)  # not again inside the back-off
        assert not behavior._search.active
    finally:
        behavior.close()


def test_the_empty_room_is_learned_only_after_two_quiet_minutes_never_from_the_first_picture():
    """Live log 2026-11-12 18:51: the room was learned from the first picture after a restart,
    with the owner in it, so the empty room looked like a person for the rest of the evening."""
    room = np.full((12, 16), 120.0, dtype=np.float32)
    body = room.copy()
    body[:, :8] = 40.0
    vision = _Vision(detected=False, motion_age=None, thumb=body)
    behavior, _device = _behavior(vision)
    try:
        behavior.watch_for_faces(100.0)
        assert not behavior._baseline.known  # the first picture starts nothing
        behavior.watch_for_faces(150.0)
        assert not behavior._baseline.known  # not yet two quiet minutes of watching
        vision.thumb = room
        behavior.watch_for_faces(221.0)
        assert behavior._baseline.known  # two quiet minutes: the room is learned
        behavior._last_person_seen = 500.0  # someone was just here
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
        assert behavior._search.reason == "close"  # the steep climb: the face is far above
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


def test_the_learned_room_is_kept_on_disk_and_a_restart_starts_from_it(tmp_path):
    room = np.full((12, 16), 120.0, dtype=np.float32)
    path = tmp_path / "scene_baseline.json"
    first = SceneBaseline(path)
    assert not first.known
    first.learn(room, 0.0)
    first.save(0.0)
    assert path.exists() and "cells" in path.read_text()
    again = SceneBaseline(path)
    assert again.known and again.differs(room) == 0.0
    body = room.copy()
    body[:, :8] = 40.0
    assert again.differs(body) >= PERSON_SHARE
    vision = _Vision(detected=False, motion_age=None, thumb=body)
    device = FakeStackChanDeviceClient()
    behavior = StackChanBehavior(
        StackChanRobotAdapter(device).robot, vision_bridge=vision, baseline_path=path
    )
    try:
        assert behavior._baseline.known  # the restart knows the room before its first picture
    finally:
        behavior.close()


def test_a_picture_that_only_differs_from_the_room_never_counts_as_a_person_for_the_rest_clock():
    room = np.full((12, 16), 120.0, dtype=np.float32)
    body = room.copy()
    body[:, :10] = 40.0
    vision = _Vision(detected=False, motion_age=None, thumb=body)
    behavior, _device = _behavior(vision)
    try:
        behavior._baseline.learn(room, 0.0)
        for step in range(6):
            behavior.watch_for_faces(100.0 + step * 10)
        assert behavior._person_share >= PERSON_SHARE
        assert behavior._last_person_seen == float("-inf")  # the rest clock keeps counting quiet
    finally:
        behavior.close()


def test_the_robots_own_head_move_is_not_a_person_and_starts_no_look():
    """Live log 2026-11-12: every look around moved the picture, the movement counted as a
    person, the rest clock reset, and three minutes later it looked again, all evening."""
    room = np.full((12, 16), 120.0, dtype=np.float32)
    vision = _Vision(detected=False, motion_age=None, thumb=room)
    behavior, _device = _behavior(vision)
    try:
        behavior._baseline.learn(room, 0.0)
        behavior._note_own_move()  # the head was just told to move (a search step, a rest pose)
        vision.motion = 0.4  # and the picture moved right after
        behavior.watch_for_faces(100.0)
        assert behavior._last_person_seen == float("-inf")
        behavior.search_tick(100.2)
        assert not behavior._search.active
        vision.motion = 0.4  # still moving 4 s later: that is not the head any more
        behavior.watch_for_faces(104.0)
        assert behavior._last_person_seen == 104.0
    finally:
        behavior.close()


def test_a_look_started_by_the_picture_alone_backs_off_3_10_30_minutes_and_stops_while_unchanged(
    caplog,
):
    room = np.full((12, 16), 120.0, dtype=np.float32)
    body = room.copy()
    body[:, :10] = 40.0
    vision = _Vision(detected=False, motion_age=None, thumb=body)
    behavior, device = _behavior(vision)
    try:
        behavior._baseline.learn(room, 0.0)
        behavior.watch_for_faces(100.0)
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            _run_person_look(behavior, device, 100.2)  # found nobody: wait 3 minutes
            behavior.search_tick(100.2 + 200.0)  # the same still picture: no look, ever
            assert not behavior._search.active
            behavior.search_tick(100.2 + 2000.0)
            assert not behavior._search.active
            chair = body.copy()
            chair[:, 10:] = 200.0  # the picture changed: one more look
            vision.thumb = chair
            behavior.watch_for_faces(2101.0)
            _run_person_look(behavior, device, 2101.2)  # found nobody: wait 10 minutes
            failed_at = behavior._still_failed_at
            vision.thumb = body
            behavior.watch_for_faces(failed_at + 400.0)
            behavior.search_tick(failed_at + 400.0)
            assert not behavior._search.active  # changed, but inside the 10 minutes
            behavior.watch_for_faces(failed_at + 601.0)
            behavior.search_tick(failed_at + 601.2)
            assert behavior._search.active  # changed and past the wait
        lines = [r.getMessage() for r in caplog.records]
        assert any("next look waits 180 s" in line for line in lines)
        assert any("next look waits 600 s" in line for line in lines)
    finally:
        behavior.close()


def test_a_spoken_find_me_ignores_the_back_off_and_does_not_add_to_it():
    search = HeadSearch(clock=lambda: 0.0)
    assert search.start("person", 0.0)
    search.stop(6.0)  # nobody found: the ambient look now waits a minute
    assert not search.may_start("person", 7.0)
    assert search.start("ask", 7.0)  # the person asked: no waiting
    search.stop(14.0)
    assert search.wait_s("person") == PERSON_BACKOFF_S[0]  # the miss was not counted
    assert search.start("ask_level", 14.0)


def _said(behavior):
    lines = []
    behavior.announce = lines.append
    return lines


def _tick_until_done(behavior, start, limit_s=40.0):
    """Presence ticks every 0.2 s on a fake clock; returns the seconds the look took."""
    now = start
    while now - start < limit_s:
        behavior.search_tick(now)
        if not behavior._search.active:
            return now - start
        now += 0.2
    raise AssertionError("the look never ended")


def test_turn_to_me_looks_after_the_reply_at_idle_level_still_and_says_so_when_nobody_is_found():
    vision = _Vision(detected=False, motion_age=None)
    behavior, device = _behavior(vision)
    try:
        lines = _said(behavior)
        behavior.idle_still = lambda: True  # the owner lifted the still rule for this
        behavior._search._last_done["person"] = 99.0  # a recent miss: the back-off is running
        behavior._search._failures = 2
        assert behavior.find_person(False) == "searching"
        behavior._active.set()  # still in the turn: nothing starts yet
        behavior.search_tick(100.0)
        assert not behavior._search.active
        behavior._active.clear()
        behavior.search_tick(100.5)
        assert behavior._search.reason == "ask"
        took = _tick_until_done(behavior, 100.7)
        assert took < ASK_FIRST_PASS_S + ASK_SECOND_PASS_S + 1.0
        assert lines == ["I can't see you yet, say something or move closer."]
        assert _head_calls(device)[-1]["pitch"] == round(CENTRE_PITCH_DEG)  # back to neutral
    finally:
        behavior.close()


def test_im_down_here_looks_level_and_to_the_sides_and_names_the_limit_when_nobody_is_found():
    vision = _Vision(detected=False, motion_age=None)
    behavior, device = _behavior(vision)
    try:
        lines = _said(behavior)
        assert behavior.find_person(True) == "searching"
        behavior.search_tick(100.0)
        assert behavior._search.reason == "ask_level"
        _tick_until_done(behavior, 100.2)
        calls = _head_calls(device)[-(len(ASK_LEVEL_STEPS) + 1) :]
        assert {c["pitch"] for c in calls} == {round(CENTRE_PITCH_DEG)}  # level, never up
        assert (
            min(c["yaw"] for c in calls) <= -ASK_PAN_DEG
            and max(c["yaw"] for c in calls) >= ASK_PAN_DEG
        )
        assert len(lines) == 1 and "I can only look level" in lines[0]
    finally:
        behavior.close()


def test_a_face_ends_the_asked_look_with_the_head_on_it_and_nothing_is_said():
    vision = _Vision(detected=False, motion_age=None)
    behavior, device = _behavior(vision)
    try:
        lines = _said(behavior)
        behavior.find_person(False)
        behavior.search_tick(100.0)
        behavior.search_tick(100.0)
        assert behavior._search.active
        vision.detected = True
        behavior.watch_for_faces(100.5)
        behavior.search_tick(100.5)
        assert not behavior._search.active and lines == []
        assert behavior._search.wait_s("person") == 0.0
    finally:
        behavior.close()


def test_a_face_seen_a_moment_ago_is_turned_to_at_once_without_a_look():
    vision = _Vision(detected=True, motion_age=None)
    behavior, device = _behavior(vision)
    try:
        behavior.watch_for_faces(time.monotonic())
        before = len(_head_calls(device))
        assert behavior.find_person(False) == "turned"
        assert len(_head_calls(device)) == before + 1 and behavior._find_request is None
        assert behavior.face_yaw() is not None
    finally:
        behavior.close()


def test_turn_to_me_moves_at_once_and_the_look_starts_on_the_first_tick_after_the_reply():
    vision = _Vision(detected=False, motion_age=None)
    behavior, device = _behavior(vision)
    try:
        behavior._active.set()  # the turn: the command is answered here
        before = len(_head_calls(device))
        assert behavior.find_person(False) == "searching"
        first = _head_calls(device)[before:]
        assert len(first) == 1 and first[0]["yaw"] != 0  # a frame-free glance and small pan
        assert first[0]["pitch"] > round(CENTRE_PITCH_DEG)
        behavior.search_tick(100.0)
        assert not behavior._search.active  # not mid-turn
        behavior._active.clear()  # the reply is over, the unit is idle
        behavior.search_tick(100.2)  # the very next tick
        assert behavior._search.reason == "ask"
        behavior.search_tick(100.2)
        assert len(_head_calls(device)) == before + 2  # the first look pose is already moving
    finally:
        behavior.close()


# The first pass is the first ten poses; the second pass the next ten.
ASK_FIRST_PASS_S = 10 * ASK_FAST_STEP_S
ASK_SECOND_PASS_S = 10 * ASK_SLOW_STEP_S


def _passes(steps):
    half = len(steps) // 2
    return steps[:half], steps[half:]


def test_the_spoken_sweep_is_wide_covers_two_heights_and_a_first_pass_takes_under_four_seconds():
    first, second = _passes(ASK_STEPS)
    assert len(first) == len(second) == 10
    for one_pass in (first, second):
        yaws = {step.yaw_deg for step in one_pass}
        assert min(yaws) <= -75 and max(yaws) >= 75 and 0.0 in yaws
        assert {step.pitch_deg for step in one_pass} == {0.0, 22.0}
        assert all(abs(step.yaw_deg) <= ASK_PAN_DEG for step in one_pass)
    assert sum(step.hold_s for step in first) <= 4.0
    assert all(step.speed == 150 for step in first)  # the top of the profile
    assert all(100 <= step.speed < 150 for step in second)  # slower, still eased
    assert sum(step.hold_s for step in second) > 2 * sum(step.hold_s for step in first)
    assert ASK_PAN_DEG > 2 * PAN_DEG  # far beyond the ambient plus or minus 25


def test_the_sweep_runs_on_the_fake_clock_fast_then_slow_and_stops_the_instant_a_face_is_seen():
    search = HeadSearch(clock=lambda: 0.0)
    assert search.start("ask", 10.0)
    times = []
    now = 10.0
    while len(times) < len(ASK_STEPS):
        step = search.due(now)
        if step is not None:
            times.append(round(now - 10.0, 2))
        now += 0.05
    first_pass_end = times[10]  # the second pass begins after the first pass's ten poses
    assert first_pass_end == round(ASK_FIRST_PASS_S, 2) and first_pass_end < 4.0
    assert not search.finished(now - 0.05)  # the last slow pose is still held
    assert search.finished(10.0 + ASK_FIRST_PASS_S + ASK_SECOND_PASS_S + 0.1)
    assert search.stop(now, found=True) == "ask" and not search.active  # a face: over at once


def test_only_a_spoken_request_gets_the_wide_sweep_and_the_second_pass():
    for reason in ("person", "speaker", "dark"):
        steps = STEP_TABLE[reason]
        assert all(abs(step.yaw_deg) <= PAN_DEG for step in steps)  # small, as before
        assert all(step.hold_s == STEP_S and step.speed == MOVE_SPEED for step in steps)
    assert len(STEP_TABLE["person"]) == 4  # no second pass for the ambient look
    assert max(abs(s.yaw_deg) for s in STEP_TABLE["ask"]) == ASK_PAN_DEG
    assert max(abs(s.yaw_deg) for s in STEP_TABLE["ask_level"]) == ASK_PAN_DEG


def test_the_spoken_sweep_moves_fast_through_the_robot_and_a_face_stops_it_at_once():
    vision = _Vision(detected=False, motion_age=None)
    behavior, device = _behavior(vision)
    try:
        behavior.find_person(False)
        behavior.search_tick(100.0)
        before = len(_head_calls(device))
        for i in range(1, 8):
            behavior.search_tick(100.0 + i * 0.2)
        fast = _head_calls(device)[before:]
        assert fast and all(c["speed"] == 150 for c in fast)
        assert any(abs(c["yaw"]) >= 40 for c in fast)
        vision.detected = True
        behavior.watch_for_faces(101.5)
        behavior.search_tick(101.6)
        assert not behavior._search.active
    finally:
        behavior.close()
