"""S-EXPR-04: attention glue, driven from presence observations."""

from __future__ import annotations

import math
import threading
import time

import pytest

from maipai_body.bodies.reachy_mini.fake import ManualClock
from maipai_body.hal.seam import FaceTrackTarget
from maipai_body.presence.attention import Attention
from maipai_body.presence.observations import PresenceObservation
from tests.test_run_loop import _make_loop


class _Recorder:
    def __init__(self):
        self.calls = []

    def set_gaze(self, pose, body_yaw):
        self.calls.append(("gaze", pose.yaw, pose.pitch, body_yaw))

    def clear_gaze(self):
        self.calls.append(("clear_gaze",))

    def set_idle(self, pose, antennas):
        self.calls.append(("idle", pose.pitch, pose.roll, pose.yaw))

    def clear_idle(self):
        self.calls.append(("clear_idle",))


def _obs(clock, *, face=None, doa=None, speech=False, age=0.0):
    return PresenceObservation(
        t_received_ns=int((clock() - age) * 1e9),
        face_detected=face is not None,
        face_x=face[0] if face else None,
        face_y=face[1] if face else None,
        doa_angle_rad=doa,
        speech_detected=speech,
    )


def test_a_fresh_face_drives_the_gaze_layer():
    clock = ManualClock(100.0)
    rec = _Recorder()
    attention = Attention(rec, clock=clock)
    clock.advance(0.1)
    attention.step(_obs(clock, face=(-0.4, 0.0)))
    gazes = [c for c in rec.calls if c[0] == "gaze"]
    assert gazes and gazes[0][1] > 0.0  # face on the left, head turns left


def test_a_stale_observation_never_moves_a_motor():
    clock = ManualClock(100.0)
    rec = _Recorder()
    attention = Attention(rec, clock=clock)
    clock.advance(0.1)
    attention.step(_obs(clock, face=(-0.4, 0.0), age=0.4))
    assert not [c for c in rec.calls if c[0] == "gaze"]


def test_idle_resumes_after_the_gaze_settles_and_never_pretends_to_be_a_cue():
    clock = ManualClock(100.0)
    rec = _Recorder()
    attention = Attention(rec, clock=clock)
    for _ in range(40):
        clock.advance(0.1)
        attention.step(_obs(clock))
    assert [c for c in rec.calls if c[0] == "idle"]
    assert {c[0] for c in rec.calls} <= {"idle", "gaze", "clear_gaze", "clear_idle"}


def test_release_clears_both_layers():
    clock = ManualClock(100.0)
    rec = _Recorder()
    attention = Attention(rec, clock=clock)
    for _ in range(8):
        clock.advance(0.1)
        attention.step(_obs(clock, face=(0.0, 0.0)))
    attention.release()
    assert ("clear_gaze",) in rec.calls and ("clear_idle",) in rec.calls


def test_speech_from_the_side_turns_the_gaze_toward_the_probe():
    clock = ManualClock(100.0)
    rec = _Recorder()
    attention = Attention(rec, clock=clock)
    clock.advance(0.1)
    # SDK angle 0.2 rad is near the robot's left edge, a side bearing; the probe turns left.
    attention.step(_obs(clock, doa=0.2, speech=True))
    gazes = [c for c in rec.calls if c[0] == "gaze"]
    assert gazes and gazes[0][3] == pytest.approx(math.radians(20.0))


def test_run_loop_with_attention_drives_the_head_and_leaves_the_daemon_tracker_off():
    loop, parts = _make_loop(presence_interval_s=0.02)
    client, engine = parts["client"], parts["engine"]
    loop._attention = Attention(engine._engine, clock=time.monotonic)
    client.face_target = FaceTrackTarget(detected=True, x=-0.4, y=0.0)
    for _ in range(6):
        loop._presence_tick(threading.Event())
        time.sleep(0.02)
    engine._engine._worker.flush()
    assert client.tracking_enabled is False
    yaws = [c.pose.yaw for c in client.sent_commands if c.pose is not None]
    assert yaws and max(yaws) > 0.05


def test_run_loop_without_attention_keeps_the_daemon_tracker():
    loop, parts = _make_loop(presence_interval_s=0.02)
    client = parts["client"]
    client.face_target = FaceTrackTarget(detected=True, x=-0.4, y=0.0)
    loop._presence_tick(threading.Event())
    assert client.tracking_enabled is True


def test_attention_keeps_following_the_same_face_when_a_larger_one_appears():
    clock = ManualClock(100.0)
    rec = _Recorder()
    attention = Attention(rec, clock=clock)
    first = PresenceObservation(
        t_received_ns=int(clock() * 1e9), face_detected=True, face_x=0.5, face_y=0.0
    )
    attention.step(first)
    clock.advance(0.1)
    # The tracker now reports the other face as primary, but ours is still in view.
    second = PresenceObservation(
        t_received_ns=int(clock() * 1e9),
        face_detected=True,
        face_x=-0.6,
        face_y=0.0,
        faces=((-0.6, 0.0), (0.48, 0.0)),
    )
    attention.step(second)
    assert attention.gaze.head_yaw < 0.0  # still turned toward +x (right = negative yaw)


def test_attention_switches_to_the_primary_when_the_followed_face_is_gone():
    clock = ManualClock(100.0)
    attention = Attention(_Recorder(), clock=clock)
    attention.step(
        PresenceObservation(
            t_received_ns=int(clock() * 1e9), face_detected=True, face_x=0.5, face_y=0.0
        )
    )
    clock.advance(0.1)
    attention.step(
        PresenceObservation(
            t_received_ns=int(clock() * 1e9),
            face_detected=True,
            face_x=-0.6,
            face_y=0.0,
            faces=((-0.6, 0.0),),
        )
    )
    for _ in range(30):
        clock.advance(0.1)
        attention.step(
            PresenceObservation(
                t_received_ns=int(clock() * 1e9),
                face_detected=True,
                face_x=-0.6,
                face_y=0.0,
                faces=((-0.6, 0.0),),
            )
        )
    assert attention.gaze.head_yaw > 0.0
