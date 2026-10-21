"""Idle face watching: the camera line, the greeting edge, and what a face does to the robot."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from maipai_body.app import StackChanBehavior
from maipai_body.bodies.stackchan import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.presence_watch import (
    GREET_AFTER_ABSENT_S,
    GREET_COOLDOWN_S,
    CameraStats,
    GreetingPolicy,
)


def test_the_camera_line_reports_frames_bytes_and_looks_once_a_minute():
    totals = [0, 0]
    stats = CameraStats(lambda: (totals[0], totals[1]))
    assert stats.report(0.0) is None  # the first call only starts the minute
    totals[:] = [600, 614_400]
    stats.looked(0.003, False)
    stats.looked(0.005, True)
    assert stats.report(30.0) is None
    line = stats.report(60.0)
    assert line is not None
    assert "600 frames" in line and "600 KB" in line
    assert "looked at 2 (a face in 1)" in line and "mean 4.0 ms" in line
    assert stats.report(61.0) is None  # the next minute starts empty


def test_a_person_returning_after_a_long_absence_is_greeted_once():
    greeting = GreetingPolicy()
    assert greeting.seen(0.0) is True  # the first sight after the robot started
    for t in range(1, 60):
        assert greeting.seen(float(t)) is False  # still there: no repeat
    assert greeting.seen(60.0 + GREET_AFTER_ABSENT_S) is False  # inside the cooldown
    later = 60.0 + GREET_COOLDOWN_S + GREET_AFTER_ABSENT_S
    assert greeting.seen(later) is True  # away long enough, cooldown over


def test_a_short_walk_out_of_view_is_not_a_new_arrival():
    greeting = GreetingPolicy(absent_s=600.0, cooldown_s=0.0)
    assert greeting.seen(0.0)
    assert not greeting.seen(300.0)


class _Vision:
    def __init__(self, detected):
        self.detected = detected
        self.calls = 0
        self.may_move_seen = []

    def track_stream_frame(self, *, deadline_s=0.4, may_move=None):
        self.calls += 1
        self.may_move_seen.append(may_move() if may_move else None)
        return SimpleNamespace(detected=self.detected, x=0.5, y=0.5)


def _behavior(vision):
    device = FakeStackChanDeviceClient()
    behavior = StackChanBehavior(StackChanRobotAdapter(device).robot, vision_bridge=vision)
    return behavior, device


def test_a_face_keeps_the_rest_policy_awake_and_greets_once_with_a_happy_face(caplog):
    vision = _Vision(True)
    behavior, device = _behavior(vision)
    try:
        behavior.idle_level = "still"
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            assert behavior.watch_for_faces(100.0) is True
            assert behavior.watch_for_faces(100.2) is False  # looks are 0.5 s apart
            assert behavior.watch_for_faces(100.6) is True
        assert behavior._last_person_seen == 100.6
        assert sum("greeting" in r.getMessage() for r in caplog.records) == 1
        frames = [c for c in device.calls if "avatar" in c.name or "emotion" in c.name]
        assert behavior.robot._driver("head").expression_device.last_expression == "happy"
        assert frames is not None
    finally:
        behavior.close()


def test_the_head_follows_a_face_only_when_the_head_may_move():
    vision = _Vision(True)
    behavior, _device = _behavior(vision)
    try:
        behavior.idle_still = lambda: True  # charging, level still, or power unknown
        behavior.watch_for_faces(1.0)
        assert vision.may_move_seen == [False]
        behavior.idle_still = lambda: False
        behavior.watch_for_faces(2.0)
        assert vision.may_move_seen == [False, True]
    finally:
        behavior.close()


def test_nothing_is_looked_at_when_the_camera_level_is_off_at_night_or_in_a_turn():
    vision = _Vision(True)
    behavior, _device = _behavior(vision)
    try:
        behavior.watch_level = lambda: "off"
        assert behavior.watch_for_faces(1.0) is False
        behavior.watch_level = lambda: "identify"
        behavior.night_active = lambda: True
        assert behavior.watch_for_faces(2.0) is False
        behavior.night_active = lambda: False
        behavior._active.set()
        assert behavior.watch_for_faces(3.0) is False
        assert vision.calls == 0
    finally:
        behavior.close()


def test_the_greeting_style_off_greets_nobody():
    vision = _Vision(True)
    behavior, _device = _behavior(vision)
    try:
        behavior.greeting_mode = "off"
        behavior.watch_for_faces(1.0)
        assert behavior.robot._driver("head").expression_device.last_expression != "happy"
    finally:
        behavior.close()


def test_no_face_means_no_presence_and_no_greeting():
    vision = _Vision(False)
    behavior, _device = _behavior(vision)
    try:
        before = behavior._last_person_seen
        assert behavior.watch_for_faces(1.0) is False
        assert behavior._last_person_seen == before
    finally:
        behavior.close()


def test_the_yunet_cache_step_works_without_huggingface_hub(tmp_path, monkeypatch):
    import builtins

    from maipai_body.link.assets import prepare_yunet_cache

    model = tmp_path / "face_detection_yunet_2026may.onnx"
    model.write_bytes(b"x")
    monkeypatch.delenv("HF_HOME", raising=False)
    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith("huggingface_hub"):
            raise ImportError("not in the hub bundle")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    assert prepare_yunet_cache(model) == model


# -- turning toward the speaker ---------------------------------------------------------------


class _FaceAt:
    """A vision stand-in that sees a face at a chosen place in the frame."""

    def __init__(self, x, y, detected=True):
        self.x, self.y, self.detected = x, y, detected

    def track_stream_frame(self, *, deadline_s=0.4, may_move=None):
        return SimpleNamespace(detected=self.detected, x=self.x, y=self.y)


def _head_moves(device):
    return [c for c in device.calls if c.name == "self.robot.set_head_angles"]


def test_a_listen_start_turns_toward_a_face_seen_a_moment_ago_and_holds_it_through_the_reply():
    import time

    vision = _FaceAt(0.9, 0.3)  # far right of the frame, high
    behavior, device = _behavior(vision)
    try:
        behavior.watch_for_faces(time.monotonic())
        behavior._active.clear()
        behavior.render_turn_state("listening")
        moves = _head_moves(device)
        assert moves, "the head should have turned"
        turn = moves[-1].arguments
        assert turn["yaw"] > 15  # 0.4 of a 60 degree view to the robot's right
        assert turn["pitch"] > 5  # a high face lifts the head a little
        count = len(moves)
        behavior.render_turn_state("thinking")
        behavior.render_turn_state("speaking")
        assert len(_head_moves(device)) == count  # the turn is held: nothing pulls it back
        behavior.render_turn_state("settle")
        assert _head_moves(device)[-1].arguments["yaw"] == 0  # level after the turn
    finally:
        behavior.close()


def test_no_recent_face_means_no_turn_and_no_hunting():
    vision = _FaceAt(0.9, 0.3)
    behavior, device = _behavior(vision)
    try:
        behavior._last_face = (0.9, 0.3, __import__("time").monotonic() - 30.0)  # long ago
        behavior.render_turn_state("listening")
        assert behavior._turn_face_held is False
        assert all(m.arguments["yaw"] == 0 for m in _head_moves(device))  # only the usual perk
    finally:
        behavior.close()


def test_the_face_age_is_kept_so_the_looking_at_you_answer_is_true():
    import time

    behavior, _device = _behavior(_FaceAt(0.5, 0.5))
    try:
        assert behavior.face_age() is None
        behavior.watch_for_faces(time.monotonic())
        assert behavior.face_age() is not None and behavior.face_age() < 1.0
    finally:
        behavior.close()


def test_the_follow_pose_uses_the_whole_field_of_view():
    import math

    from maipai_body.bodies.stackchan.vision_bridge import follow_pose
    from maipai_body.hal.seam import FaceTrackTarget

    right = follow_pose(FaceTrackTarget(detected=True, x=1.0, y=0.5))
    left = follow_pose(FaceTrackTarget(detected=True, x=0.0, y=0.5))
    assert math.degrees(right.yaw) == pytest.approx(30)
    assert math.degrees(left.yaw) == pytest.approx(-30)
    low = follow_pose(FaceTrackTarget(detected=True, x=0.5, y=0.9))
    assert math.degrees(low.pitch) == pytest.approx(5)  # below the middle: level, never below


def test_the_bridge_answers_can_you_see_me_without_the_hub(monkeypatch):
    import asyncio

    import maipai_body.bodies.stackchan.turn as turn_module
    from maipai_body.bodies.stackchan.sight import SightAnswers
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
            return SttStreamResult(kind="final", text="Can you see me?")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    FakeTurn.streams = []
    FakeTts.sentences = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    bridge = turn_module.StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=Stt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
        sight_control=SightAnswers(face_age=lambda: 1.5, camera_on=lambda: True),
    )
    loop.run_until_complete(bridge._run("session", "device", FakeCapture()))
    loop.close()
    assert FakeTurn.streams == []  # the hub never saw "can you see me"
    from maipai_body.bodies.stackchan.sight import YES

    assert FakeTts.sentences and FakeTts.sentences[0] in YES
