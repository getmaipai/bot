"""RM-02: every primitive renders on the Reachy Mini profile, within its envelope."""

from __future__ import annotations

import pytest

from maipai_body.bodies.reachy_mini.envelope import clamp_target
from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.primitives import PRIMITIVE_NAMES
from maipai_body.expression.reachy_mini_renderer import build_steps, render

# track and stop take a different path (set_target with a caller-given
# target, or hold with no target at all); the rest are exercised generically.
GOTO_PRIMITIVES = [p for p in PRIMITIVE_NAMES if p not in ("track", "stop", "breathe", "speak")]
SET_TARGET_PRIMITIVES = ("track", "breathe", "speak")


@pytest.mark.parametrize("primitive", PRIMITIVE_NAMES)
def test_every_primitive_renders_without_raising(primitive):
    client = FakeReachyMiniClient()
    render(primitive, client, REACHY_MINI_PROFILE)
    assert client.sent_commands, f"{primitive} reached no command at all"


@pytest.mark.parametrize("primitive", PRIMITIVE_NAMES)
@pytest.mark.parametrize("doa_angle_rad", [0.5, -0.5])
def test_every_primitive_stays_within_the_declared_envelope(primitive, doa_angle_rad):
    """Every step a primitive builds passes the same clamp a live goto/set_target would.

    Both directions are exercised: a target to the left and to the right
    take different branches in glance, tilt and attend (a target's own
    side), and both must clamp cleanly even though today's antenna and
    head axes happen to be symmetric.
    """
    for step in build_steps(primitive, REACHY_MINI_PROFILE, doa_angle_rad=doa_angle_rad):
        clamp_target(REACHY_MINI_PROFILE, step.pose, step.antennas, step.body_yaw)


def test_stop_calls_hold_and_nothing_else():
    client = FakeReachyMiniClient()
    render("stop", client, REACHY_MINI_PROFILE)
    assert [c.kind for c in client.sent_commands] == ["hold"]


@pytest.mark.parametrize("primitive", SET_TARGET_PRIMITIVES)
def test_set_target_primitives_never_use_goto(primitive):
    """RM-02: "set_target only for track, breathe, speak and stop"."""
    client = FakeReachyMiniClient()
    render(primitive, client, REACHY_MINI_PROFILE, doa_angle_rad=0.3)
    kinds = {c.kind for c in client.sent_commands}
    assert kinds <= {"set_target"}


@pytest.mark.parametrize("primitive", GOTO_PRIMITIVES)
def test_the_other_primitives_only_use_goto(primitive):
    client = FakeReachyMiniClient()
    render(primitive, client, REACHY_MINI_PROFILE)
    kinds = {c.kind for c in client.sent_commands}
    assert kinds <= {"goto"}, f"{primitive} used {kinds}, expected only goto"


def test_track_points_the_head_toward_the_direction_of_arrival():
    client = FakeReachyMiniClient()
    render("track", client, REACHY_MINI_PROFILE, doa_angle_rad=0.7)
    last = client.sent_commands[-1]
    assert last.kind == "set_target"
    assert last.pose.yaw == pytest.approx(0.7)


def test_glance_returns_to_neutral_after_the_target():
    client = FakeReachyMiniClient()
    render("glance", client, REACHY_MINI_PROFILE, doa_angle_rad=0.5)
    assert len(client.sent_commands) == 2
    final = client.sent_commands[-1]
    assert final.pose.yaw == 0.0
    assert final.antennas.left == 0.0
    assert final.antennas.right == 0.0


def test_glance_turns_toward_a_target_on_the_right():
    client = FakeReachyMiniClient()
    render("glance", client, REACHY_MINI_PROFILE, doa_angle_rad=0.5)
    first = client.sent_commands[0]
    assert first.pose.yaw > 0
    assert first.antennas.left > 0
    assert first.antennas.right == 0.0


def test_glance_turns_toward_a_target_on_the_left():
    client = FakeReachyMiniClient()
    render("glance", client, REACHY_MINI_PROFILE, doa_angle_rad=-0.5)
    first = client.sent_commands[0]
    assert first.pose.yaw < 0
    assert first.antennas.right < 0
    assert first.antennas.left == 0.0
