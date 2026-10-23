"""StackChan's host-only idle sleep behavior."""

from __future__ import annotations

import json

from maipai_body.bodies.stackchan.avatar.codec import decode_frame
from maipai_body.bodies.stackchan.avatar.server import control_avatar, sleeping_avatar
from maipai_body.bodies.stackchan.profile import STACKCHAN_PROFILE
from maipai_body.bodies.stackchan.routines import RestRenderer
from maipai_body.expression.rest import RestOutput, RestPolicy


def _update(policy, now, **kwargs):
    kwargs.setdefault("person_present", False)
    kwargs.setdefault("turn_active", False)
    return policy.update(now, **kwargs)


def _payload(frame):
    return json.loads(decode_frame(frame).payload)


def test_stackchan_thresholds_and_night_thresholds():
    policy = RestPolicy(0, drowsy_after_s=120, asleep_after_s=300)
    assert _update(policy, 119.9).stage == "awake"
    assert _update(policy, 120).stage == "drowsy"
    assert _update(policy, 299.9).stage == "drowsy"
    assert _update(policy, 300).stage == "asleep"
    night = RestPolicy(0, drowsy_after_s=120, asleep_after_s=300, quiet_hours_active=lambda: True)
    assert _update(night, 59.9).stage == "awake"
    assert _update(night, 60).stage == "drowsy"
    assert _update(night, 149.9).stage == "drowsy"
    assert _update(night, 150).stage == "asleep"


def test_asleep_avatar_has_zero_eye_and_mouth_weights():
    face = _payload(sleeping_avatar())
    assert face["leftEye"]["weight"] == face["rightEye"]["weight"] == 0
    assert face["mouth"]["weight"] == 0


class _Client:
    def __init__(self):
        self.frames = []
        self.poses = []

    def send_avatar_frame(self, frame):
        self.frames.append(frame)

    def command(self, name, **kwargs):
        self.poses.append(kwargs["pose"])


def _out(stage, wake=False):
    return RestOutput(stage, 0, "neutral", wake_transition=wake)


def test_sleep_dims_without_changing_owner_and_wake_blinks_then_restores():
    owner_brightness = 73
    applied_brightness = []
    ring = []
    client = _Client()
    renderer = RestRenderer(
        set_brightness=applied_brightness.append,
        restore_brightness=lambda: owner_brightness,
        set_ring_sleeping=ring.append,
        sleep=lambda _seconds: None,
    )
    renderer.render(_out("asleep"), client, STACKCHAN_PROFILE)
    assert applied_brightness == [5]
    assert owner_brightness == 73
    assert ring == [True]
    assert _payload(client.frames[-1])["leftEye"]["weight"] == 0
    renderer.render(_out("awake", wake=True), client, STACKCHAN_PROFILE)
    assert client.frames[-2:] == [sleeping_avatar(), control_avatar("neutral")]
    assert applied_brightness == [5, 73]
    assert owner_brightness == 73
    assert ring == [True, False]


def test_turn_active_prevents_stackchan_rest_stage_change():
    policy = RestPolicy(0, drowsy_after_s=120, asleep_after_s=300)
    assert _update(policy, 600, turn_active=True).stage == "awake"
