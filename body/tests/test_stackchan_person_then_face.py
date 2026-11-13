"""The behavior wires the person tracker to the real head: an arm-only view turns the head toward
the person and tilts up, a face hands over to following, the speaker turn uses the body, the sweep
hands over, and "what do you see" answers from the robot's own pass."""

from __future__ import annotations

import logging
import math
import random
from types import SimpleNamespace

import numpy as np

from maipai_body.app import StackChanBehavior
from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.person_tracker import AIM_SPEED, AIM_TILT_STEP_DEG, PersonBox
from maipai_body.bodies.stackchan.profile import CENTRE_PITCH_DEG, FOLLOW_YAW_SIGN
from maipai_body.bodies.stackchan.sight import PERSON_NO_FACE, SightAnswers
from maipai_body.bodies.stackchan.vision_bridge import StackChanVisionBridge
from maipai_body.vision.look_fast import Detection


class _Vision:
    """A bridge whose newest look carries person boxes (and maybe a face), with the Look model
    loaded or not."""

    def __init__(self, *, people=(), face=None, ready=True, luma=120.0, thumb=None):
        self.people_now = list(people)
        self.face = face  # (x, y) of a face in the picture, or None
        self.ready = ready
        self.luma = luma
        self.thumb = thumb
        self.last_motion = 0.0
        self.last_look_ms = 9.5
        self.last_best_person = 0.0
        self.last_pose_deg = None
        self.frame_at = 0.0
        self.last_person_box = None
        self.last_person_time = None
        self.may_move_asked = []

    def track_stream_frame(self, *, deadline_s=0.4, may_move=None):
        if may_move is not None:
            self.may_move_asked.append(may_move())
        if self.face is None:
            return SimpleNamespace(detected=False, x=None, y=None)
        return SimpleNamespace(detected=True, x=self.face[0], y=self.face[1])

    def motion_age(self):
        return None

    def latest_look(self, *, max_age_s, take=False):
        return (b"\xff\xd8", 1 if self.face else 0, self.luma, self.thumb)

    def people(self, *, max_age_s):
        return list(self.people_now)

    def last_person(self, *, max_age_s):
        return self.last_person_box or (
            max(self.people_now, key=lambda b: b.area) if self.people_now else None
        )

    def person_age(self):
        return 0.5 if self.people_now else self.last_person_time

    def objects(self, max_age_s):
        return None

    def look_ready(self):
        return self.ready

    def look_at(self):
        return self.frame_at


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


def _tick(behavior, vision, now):
    vision.frame_at = now  # a fresh frame arrived for this look
    behavior.watch_for_faces(now)
    behavior.search_tick(now)


def arm_box(cx=0.2):
    return PersonBox(cx - 0.2, 0.0, 0.4, 1.0, 0.85)  # a torso filling the left, cut off at the top


def test_an_arm_only_view_turns_the_head_toward_the_person_and_tilts_up_then_finds_the_face(caplog):
    vision = _Vision(people=[arm_box(0.2)])
    behavior, device = _behavior(vision)
    try:
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            _tick(behavior, vision, 100.0)
            assert not _head_calls(device)  # one look is not enough
            _tick(behavior, vision, 100.6)
            calls = _head_calls(device)
            assert len(calls) == 1
            assert calls[0]["yaw"] * FOLLOW_YAW_SIGN < 0  # left of the picture: toward it
            assert calls[0]["pitch"] == round(
                CENTRE_PITCH_DEG + AIM_TILT_STEP_DEG
            )  # cut off at the top: up
            assert calls[0]["speed"] == AIM_SPEED
            assert behavior._tracker.stage == "aiming"
            # The move settles, the person is now centred, and then the face appears above.
            vision.people_now = [PersonBox(0.3, 0.0, 0.4, 1.0, 0.85)]
            _tick(behavior, vision, 102.5)
            _tick(behavior, vision, 103.5)
            assert behavior._tracker.stage == "follow"
            vision.face = (0.5, 0.2)
            _tick(behavior, vision, 104.5)
            assert behavior._tracker.stage == "follow"
            lines = [r.getMessage() for r in caplog.records]
            assert any(
                "person seen at x 0.20, box top 0.00" in line and "-> aiming" in line
                for line in lines
            )
            assert any("aiming -> follow: centred" in line for line in lines)
            assert any("aim at x 0.20, yaw" in line for line in lines)
            # The tracker owns following now: the bridge's own absolute follow stays off.
            assert vision.may_move_asked and not any(vision.may_move_asked)
            assert not behavior._search.active
    finally:
        behavior.close()


def test_a_weak_person_hint_starts_the_glance_up_look_and_a_box_hands_over(caplog):
    """Measured 2026-11-12: a dark hoodie filling the frame scores 0.05 to 0.17 as a person, so
    no box; the glance-up look runs for it, and a box in a later look hands over to the tracker."""
    vision = _Vision(people=[])
    vision.last_best_person = 0.14
    behavior, device = _behavior(vision)
    behavior.on_sees = lambda state: seen.append(state)
    seen = []
    try:
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            _tick(behavior, vision, 100.0)
            assert behavior._search.active and behavior._search.reason == "person"
            assert any(
                "the detector hints at a person (0.14)" in r.getMessage() for r in caplog.records
            )
            assert seen == ["maybe"]
            vision.people_now = [PersonBox(0.3, 0.0, 0.4, 1.0, 0.85)]
            _tick(behavior, vision, 100.6)
            assert not behavior._search.active and behavior._tracker.stage == "aiming"
            assert seen == ["maybe", "person"]
            vision.face = (0.5, 0.2)
            _tick(behavior, vision, 101.2)
            assert seen == ["maybe", "person", "face"]
            vision.face = None
            vision.people_now = []
            vision.last_best_person = 0.02
            _tick(behavior, vision, 101.8)
            assert seen[-1] == "face"  # a miss right after: the glow holds two seconds
            _tick(behavior, vision, 104.0)
            assert seen[-1] is None
    finally:
        behavior.close()


def test_a_flat_dark_picture_with_a_person_hint_is_not_called_a_dark_room():
    vision = _Vision(people=[], luma=None)
    vision.last_best_person = 0.12
    behavior, device = _behavior(vision)
    behavior.lux = lambda: 4.0
    try:
        _tick(behavior, vision, 100.0)
        assert behavior._search.reason in ("person", "close")  # a look for the face, no dark check
    finally:
        behavior.close()


def test_a_body_seen_a_moment_ago_turns_the_head_at_listen_start_instead_of_the_blind_glance(
    caplog,
):
    vision = _Vision(
        people=[],
    )
    vision.last_person_box = PersonBox(0.6, 0.1, 0.3, 0.9, 0.8)  # to the right, seen just now
    behavior, device = _behavior(vision)
    try:
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            behavior.robot.lease.acquire(priority="expression", holder="turn")
            assert behavior._turn_toward_face()
        calls = _head_calls(device)
        assert calls and calls[-1]["yaw"] * FOLLOW_YAW_SIGN > 0  # right of the picture: toward it
        assert calls[-1]["pitch"] > round(CENTRE_PITCH_DEG)
        assert behavior._search_after_turn
        assert any(
            "turned toward the person who spoke: a body at x 0.75" in r.getMessage()
            for r in caplog.records
        )
        assert math.isclose(behavior._tracker.pose[0], calls[-1]["yaw"], abs_tol=0.6)
    finally:
        behavior.robot.lease.release(holder="turn")
        behavior.close()


def test_the_find_me_sweep_stops_at_a_person_and_hands_over_to_the_tracker(caplog):
    vision = _Vision(people=[])
    behavior, device = _behavior(vision)
    try:
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            assert behavior.find_person(False) == "searching"
            _tick(behavior, vision, 10.0)
            assert behavior._search.active and behavior._search.reason == "ask"
            vision.people_now = [PersonBox(0.6, 0.2, 0.3, 0.8, 0.9)]
            _tick(behavior, vision, 10.5)
            assert not behavior._search.active and behavior._tracker.stage == "aiming"
            lines = [r.getMessage() for r in caplog.records]
            assert any(
                "found a person at x 0.75; looking for the face there" in line for line in lines
            )
            assert any("person found by the sweep at x 0.75" in line for line in lines)
    finally:
        behavior.close()


def test_the_bridge_runs_the_look_detector_on_the_same_frame_and_keeps_boxes_and_objects(tmp_path):
    class Faces:
        def detect(self, frame):
            return []

    class Look:
        ready = True
        last_ms = 8.0

        def detect(self, frame):
            return [
                Detection("person", 0.9, (0.1, 0.0, 0.4, 1.0)),
                Detection("laptop", 0.7, (0.6, 0.5, 0.3, 0.3)),
                Detection("person", 0.55, (0.8, 0.3, 0.1, 0.3)),
            ]

    client = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(client).robot
    clock = [100.0]
    bridge = StackChanVisionBridge(
        robot,
        detector=Faces(),
        embedder=None,
        gallery=None,
        decode=lambda _: np.zeros((240, 320, 3), dtype=np.uint8),
        look_detector=Look(),
        frame_provider=lambda deadline: b"\xff\xd8jpeg",
        clock=lambda: clock[0],
    )
    target = bridge.track_stream_frame()
    assert not target.detected
    people = bridge.people(max_age_s=1.0)
    assert [round(b.centre_x, 2) for b in people] == [0.3, 0.85]
    assert round(bridge.last_person(max_age_s=1.0).centre_x, 2) == 0.3  # the largest
    assert bridge.person_age() == 0.0 and bridge.look_ready() and bridge.last_look_ms == 8.0
    objects = bridge.objects(1.0)
    assert [(o["label"], o["count"]) for o in objects] == [("person", 2), ("laptop", 1)]
    clock[0] = 103.0
    assert bridge.people(max_age_s=1.0) == [] and bridge.objects(1.0) is None
    assert bridge.last_person(max_age_s=5.0) is not None and bridge.person_age() == 3.0


def test_sight_answers_know_a_body_without_a_face_and_say_what_the_fast_pass_sees():
    objects = [{"label": "person", "count": 1}, {"label": "laptop", "count": 1}]
    answers = SightAnswers(
        face_age=lambda: None,
        camera_on=lambda: True,
        light=lambda: "bright",
        camera_running_s=lambda: 300.0,
        watching=lambda: True,
        person_age=lambda: 2.0,
        objects=lambda max_age_s: objects,
        rng=random.Random(1),
    )
    assert answers.answer("can you see me") in PERSON_NO_FACE
    assert answers.quick_look() == "I see a person and a laptop."
    nobody = SightAnswers(
        face_age=lambda: None,
        camera_on=lambda: True,
        camera_running_s=lambda: 300.0,
        person_age=lambda: None,
        objects=lambda max_age_s: None,
        rng=random.Random(1),
    )
    assert nobody.quick_look() is None
    assert "can't spot anyone" in nobody.answer("can you see me")


def test_the_camera_minute_line_counts_people_and_the_detector_time(caplog):
    vision = _Vision(people=[arm_box(0.5)])
    behavior, device = _behavior(vision)
    try:
        behavior._camera_stats._since = 0.0
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            behavior.watch_for_faces(1.0)
            line = behavior._camera_stats.report(61.0)
        assert line is not None and "a person in 1 looks, detector mean 9.5 ms" in line
        # The false-person window: a person box in every look while no face was seen.
        behavior._fp_window_at = -400.0
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            behavior.watch_for_faces(2.0)
        assert any(
            "person detector: no face for 5 min, a person box in 2 of 2 looks (100.0%)"
            in r.getMessage()
            for r in caplog.records
        )
    finally:
        behavior.close()


def test_a_face_in_the_middle_keeps_the_head_still_while_following():
    vision = _Vision(people=[], face=(0.5, 0.5))
    behavior, device = _behavior(vision)
    behavior.greeting_mode = "off"  # the greeting nod is not the tracker's move
    try:
        for i in range(4):
            _tick(behavior, vision, 10.0 + i)
        assert behavior._tracker.stage == "follow"
        assert not _head_calls(device)  # centred: nothing to do, no twitching
        vision.face = (0.9, 0.5)  # they step to the right: a clear move, acted on at once
        _tick(behavior, vision, 15.0)
        calls = _head_calls(device)
        assert len(calls) == 1 and calls[0]["yaw"] * FOLLOW_YAW_SIGN > 0  # stepped right
        assert math.isclose(behavior._tracker.pose[0], calls[0]["yaw"], abs_tol=0.5)
    finally:
        behavior.close()
