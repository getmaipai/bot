"""The head's resting pose is level, and nothing "drops" it upward (owner report 2026-10-21)."""

from __future__ import annotations

import math

from maipai_body.bodies.stackchan.expression_map import PRIMITIVE_BODY_MAP
from maipai_body.bodies.stackchan.profile import CENTRE_PITCH_DEG, STACKCHAN_PROFILE
from maipai_body.bodies.stackchan.renderer import pitch_for
from maipai_body.bodies.stackchan.routines import RestRenderer
from maipai_body.expression.rest import PITCH_FRACTION, RestOutput
from maipai_body.hal.seam import HeadPose


class _Client:
    def __init__(self):
        self.poses = []

    def command(self, verb, **kwargs):
        self.poses.append(kwargs["pose"])


def test_level_is_the_bottom_of_the_range_not_its_middle():
    # The pitch servo only travels up from level (3 to 87 degrees): the middle, 45, is 45 up.
    assert CENTRE_PITCH_DEG <= 10
    assert math.isclose(pitch_for(STACKCHAN_PROFILE), math.radians(CENTRE_PITCH_DEG))


def test_every_expression_primitive_stays_at_or_above_level_and_below_the_top():
    low = math.radians(CENTRE_PITCH_DEG)
    high = math.radians(STACKCHAN_PROFILE.axis("head_pitch").max)
    for name, action in PRIMITIVE_BODY_MAP.items():
        pitch = pitch_for(STACKCHAN_PROFILE, action.pitch_fraction)
        assert low <= pitch <= high, name
        assert pitch < math.radians(CENTRE_PITCH_DEG + 15), f"{name} is a small move, not a look-up"


def test_the_perk_lifts_the_head_and_a_negative_fraction_never_goes_below_level():
    assert pitch_for(STACKCHAN_PROFILE, PRIMITIVE_BODY_MAP["perk"].pitch_fraction) > pitch_for(
        STACKCHAN_PROFILE
    )
    assert pitch_for(STACKCHAN_PROFILE, -0.5) == pitch_for(STACKCHAN_PROFILE)


def test_no_rest_stage_raises_the_head():
    level = pitch_for(STACKCHAN_PROFILE)
    for stage, fraction in PITCH_FRACTION.items():
        client = _Client()
        RestRenderer().render(
            RestOutput(stage=stage, pose_pitch_fraction=fraction, face="sleepy"),
            client,
            STACKCHAN_PROFILE,
        )
        assert client.poses and client.poses[-1].pitch == level, stage


def test_the_head_pose_type_still_accepts_the_level_pose():
    assert HeadPose(pitch=pitch_for(STACKCHAN_PROFILE)).pitch > 0


def test_the_idle_face_is_neutral_awake_and_sleepy_when_drowsy():
    # Awake stays the calm neutral face; drowsy shows the sleepy one (owner decision 2026-10-23).
    # The closed-eye asleep face is covered in test_stackchan_idle_sleep.py.
    from maipai_body.bodies.stackchan.avatar.server import control_avatar

    for stage, face in (("awake", "neutral"), ("drowsy", "sleepy")):
        sent = []
        client = _Client()
        client.send_avatar_frame = sent.append
        RestRenderer().render(
            RestOutput(stage=stage, pose_pitch_fraction=PITCH_FRACTION[stage], face=face),
            client,
            STACKCHAN_PROFILE,
        )
        assert sent == [control_avatar(face)], stage
