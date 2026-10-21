"""BOT-SC-ANIM-01: rest routines (drowsy, asleep, waking) on a manual clock."""

from __future__ import annotations

import pytest

from maipai_body.bodies.stackchan.profile import STACKCHAN_PROFILE
from maipai_body.bodies.stackchan.routines import RestRenderer, render_rest
from maipai_body.expression.rest import RestOutput, RestPolicy


def _update(policy, t, **kwargs):
    kwargs.setdefault("person_present", False)
    kwargs.setdefault("turn_active", False)
    return policy.update(t, **kwargs)


def test_awake_stays_awake_then_drowsy_at_600_s():
    policy = RestPolicy(0.0)
    assert policy.stage == "awake"
    assert _update(policy, 0.0).stage == "awake"
    assert _update(policy, 599.9).stage == "awake"
    out = _update(policy, 600.0)
    assert out.stage == "drowsy"
    assert out.face == "sleepy"
    assert out.pose_pitch_fraction == pytest.approx(0.25)
    assert out.wake_transition is False
    assert policy.stage == "drowsy"


def test_drowsy_drifts_to_asleep_at_1800_s():
    policy = RestPolicy(0.0)
    assert _update(policy, 600.0).stage == "drowsy"
    assert _update(policy, 1799.9).stage == "drowsy"
    out = _update(policy, 1800.0)
    assert out.stage == "asleep"
    assert out.face == "sleepy"
    assert out.pose_pitch_fraction == pytest.approx(0.6)
    # A further quiet update stays asleep at the same depth.
    again = _update(policy, 2000.0)
    assert again.stage == "asleep" and again.pose_pitch_fraction == pytest.approx(0.6)


def test_activity_wakes_instantly_and_the_wake_flag_fires_exactly_once():
    policy = RestPolicy(0.0)
    assert _update(policy, 1800.0).stage == "asleep"
    wake = _update(policy, 1800.05, person_present=True)
    assert wake.stage == "awake"
    assert wake.wake_transition is True
    assert wake.face == "neutral"
    assert wake.pose_pitch_fraction == 0.0
    quiet = _update(policy, 1801.0)
    assert quiet.stage == "awake" and quiet.wake_transition is False


def test_loud_sound_counts_as_waking_activity():
    policy = RestPolicy(0.0)
    _update(policy, 1800.0)
    wake = _update(policy, 1800.1, sound_level=0.5)
    assert wake.stage == "awake" and wake.wake_transition is True
    # Just below the threshold the robot stays asleep.
    policy = RestPolicy(0.0)
    _update(policy, 1800.0)
    assert _update(policy, 1800.1, sound_level=0.49).stage == "asleep"


def test_quiet_hours_halve_both_thresholds():
    policy = RestPolicy(0.0, quiet_hours_active=lambda: True)
    assert _update(policy, 299.9).stage == "awake"
    assert _update(policy, 300.0).stage == "drowsy"
    assert _update(policy, 899.9).stage == "drowsy"
    assert _update(policy, 900.0).stage == "asleep"


def test_turn_active_blocks_any_stage_change():
    policy = RestPolicy(0.0)
    assert _update(policy, 600.0, turn_active=True).stage == "awake"
    assert _update(policy, 1800.0, turn_active=True).stage == "awake"
    # The turn kept the idle timer quiet, so a full fresh window must pass.
    assert _update(policy, 2400.0).stage == "drowsy"


class _FakeClient:
    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.poses: list[object] = []

    def send_avatar_frame(self, frame: bytes) -> None:
        self.frames.append(frame)

    def command(self, name: str, **kwargs) -> None:
        assert name == "set"
        self.poses.append(kwargs["pose"])


def _rest_output(stage: str, fraction: float, face: str) -> RestOutput:
    return RestOutput(stage=stage, pose_pitch_fraction=fraction, face=face)


def test_rest_renderer_does_not_resend_the_same_stage():
    client = _FakeClient()
    renderer = RestRenderer()
    renderer.render(_rest_output("drowsy", 0.25, "sleepy"), client, STACKCHAN_PROFILE)
    renderer.render(_rest_output("drowsy", 0.25, "sleepy"), client, STACKCHAN_PROFILE)
    assert len(client.frames) == 1
    assert len(client.poses) == 1
    renderer.render(_rest_output("asleep", 0.6, "sleepy"), client, STACKCHAN_PROFILE)
    assert len(client.frames) == 2
    assert len(client.poses) == 2
    # The head only travels up from level, so every rest stage rests at level; the face differs.
    assert client.poses[1].pitch == client.poses[0].pitch


def test_render_rest_routes_through_a_renderer_and_dedups():
    client = _FakeClient()
    renderer = RestRenderer()
    render_rest(_rest_output("awake", 0.0, "neutral"), client, STACKCHAN_PROFILE, renderer=renderer)
    render_rest(_rest_output("awake", 0.0, "neutral"), client, STACKCHAN_PROFILE, renderer=renderer)
    assert len(client.frames) == 1
