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


def test_sleep_face_is_firmware_gated_and_brightness_failure_does_not_block_face(caplog):
    client = _Client()

    def fail(_value):
        raise TimeoutError("tool timed out")

    renderer = RestRenderer(set_brightness=fail, firmware_version=lambda: "0.2.53")
    renderer.render(_out("asleep"), client, STACKCHAN_PROFILE)
    assert client.frames[-1].expression == "sleepy"
    assert "brightness set to 5 failed" in caplog.text

    new_firmware = _Client()
    RestRenderer(firmware_version=lambda: "0.2.54").render(
        _out("asleep"), new_firmware, STACKCHAN_PROFILE
    )
    assert new_firmware.frames[-1].expression == "sleeping"


def test_failed_sleep_face_is_retried_and_later_face_stays_asleep():
    class RecordingClient(_Client):
        def __init__(self):
            super().__init__()
            self.fail_once = True
            self.writes = []

        def send_avatar_frame(self, frame):
            if self.fail_once:
                self.fail_once = False
                raise TimeoutError("lost frame")
            self.frames.append(frame)
            self.writes.append(("face", frame.expression))

        def command(self, name, **kwargs):
            self.poses.append(kwargs["pose"])
            self.writes.append(("pose", kwargs["pose"]))

    client = RecordingClient()
    renderer = RestRenderer(firmware_version=lambda: "0.2.54")
    renderer.render(_out("asleep"), client, STACKCHAN_PROFILE)
    renderer.render(_out("asleep"), client, STACKCHAN_PROFILE)
    assert ("face", "sleeping") in client.writes
    renderer.render(_out("asleep"), client, STACKCHAN_PROFILE)
    assert client.writes[-2] == ("face", "sleeping")


def test_turn_active_prevents_stackchan_rest_stage_change():
    policy = RestPolicy(0, drowsy_after_s=120, asleep_after_s=300)
    assert _update(policy, 600, turn_active=True).stage == "awake"


def test_a_failed_wake_blink_is_retried_and_still_restores_the_screen():
    sent, levels = [], []
    fail = [True]

    class Client:
        def send_avatar_frame(self, frame):
            if fail[0] and frame.expression == "neutral":
                raise ConnectionError("unit not answering")
            sent.append(frame.expression)

        def command(self, *args, **kwargs):
            return None

    renderer = RestRenderer(
        set_brightness=levels.append,
        restore_brightness=lambda: 80,
        sleep=lambda _s: None,
        firmware_version=lambda: "0.2.54",
    )
    client = Client()
    asleep = RestOutput(stage="asleep", pose_pitch_fraction=0.0, face="sleepy")
    renderer.render(asleep, client, STACKCHAN_PROFILE)
    awake = RestOutput(stage="awake", pose_pitch_fraction=0.0, face="neutral", wake_transition=True)
    renderer.render(awake, client, STACKCHAN_PROFILE)  # the neutral face fails
    fail[0] = False
    renderer.render(
        RestOutput(stage="awake", pose_pitch_fraction=0.0, face="neutral"),
        client,
        STACKCHAN_PROFILE,
    )
    assert sent[-1] == "neutral"
    assert levels[-1] == 80
