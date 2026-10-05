"""LINK-STATE-01 rung 0: body-only cues from the existing expression primitives."""

from __future__ import annotations

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.expression.suppression import SuppressionContext
from maipai_body.link.rung0 import Rung0Cues, Rung0Settings
from maipai_body.link.state_machine import LinkStateMachine
from tests.ladder_fakes import FakeClock, FakeSpeaker

SLEEP_AFTER_S = 600.0
SETTINGS = Rung0Settings(away_after_s=120.0, tracking_off_after_s=300.0)


def _rig(*, may_drive=lambda: True, speaker=None, muted=False):
    clock = FakeClock()
    client = FakeReachyMiniClient(REACHY_MINI_PROFILE)
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    machine = LinkStateMachine(
        clock=clock, wall_clock=clock.wall_clock, sleep_after_s=SLEEP_AFTER_S
    )
    spoken: list[bool] = []
    cues = Rung0Cues(
        render=lambda primitive: (
            engine.render_ambient(primitive, SuppressionContext(muted=muted)).rendered
        ),
        machine=machine,
        clock=clock,
        settings=SETTINGS,
        may_drive=may_drive,
        speaker=speaker,
        on_reconnect_spoken=lambda: spoken.append(True),
    )
    return cues, machine, client, clock, spoken


def _kinds(client):
    return [c.kind for c in client.sent_commands]


def test_losing_the_link_settles_then_breathes():
    cues, machine, client, *_ = _rig()
    machine.link_lost("x")
    cues.tick()
    assert _kinds(client) == ["goto", "set_target"]
    settle, breathe = client.sent_commands
    assert settle.antennas.left == 0.0 and settle.antennas.right == 0.0  # the settle pose
    assert breathe.pose.pitch != 0.0  # the breathe offset


def test_it_does_not_repeat_the_settle_on_every_tick():
    cues, machine, client, *_ = _rig()
    machine.link_lost("x")
    cues.tick()
    cues.tick()
    assert len(client.sent_commands) == 2


def test_the_antennas_go_to_the_away_pose_after_the_configured_time():
    cues, machine, client, clock, _ = _rig()
    machine.link_lost("x")
    cues.tick()
    n = len(client.sent_commands)
    clock.advance(119.0)
    cues.tick()
    assert len(client.sent_commands) == n
    clock.advance(1.0)
    cues.tick()
    away = client.sent_commands[-1]
    assert len(client.sent_commands) == n + 1
    assert away.antennas.left < 0.0 and away.antennas.right < 0.0


def test_tracking_is_allowed_until_the_configured_time_then_off():
    cues, machine, _, clock, _ = _rig()
    assert cues.tracking_allowed() is True
    machine.link_lost("x")
    clock.advance(299.0)
    assert cues.tracking_allowed() is True
    clock.advance(1.0)
    assert cues.tracking_allowed() is False


def test_sleeping_takes_the_away_pose_at_once_and_keeps_tracking_off():
    cues, machine, client, clock, _ = _rig()
    machine.link_lost("x")
    cues.tick()
    clock.advance(SLEEP_AFTER_S)
    machine.tick()
    cues.tick()
    assert client.sent_commands[-1].antennas.left < 0.0
    assert cues.tracking_allowed() is False


def test_a_redeem_stirs_exactly_once_and_says_the_reconnect_clip_once():
    speaker = FakeSpeaker()
    cues, machine, client, _, spoken = _rig(speaker=speaker)
    machine.link_lost("x")
    cues.tick()
    client.sent_commands.clear()
    machine.redeemed("lan", "http://192.0.2.10:80")
    machine.redeemed("lan", "http://192.0.2.10:80")
    cues.tick()
    cues.tick()
    perks = [c for c in client.sent_commands if c.pose.pitch < 0.0]  # perk lifts the head
    assert len(perks) == 1
    assert _kinds(client) == ["goto", "goto"]  # the stir, then the settle
    assert speaker.said == [["line.reconnect"]]
    assert spoken == [True]


def test_an_unrendered_reconnect_clip_is_not_spoken_and_not_claimed():
    speaker = FakeSpeaker(available=set())
    cues, machine, client, _, spoken = _rig(speaker=speaker)
    machine.link_lost("x")
    machine.redeemed("lan", None)
    cues.tick()
    assert speaker.said == []
    assert spoken == []
    assert len(client.sent_commands) >= 2  # the body cue still happened


def test_nothing_drives_the_head_while_a_turn_owns_it_and_the_cue_waits():
    free = [False]
    cues, machine, client, *_ = _rig(may_drive=lambda: free[0])
    machine.link_lost("x")
    cues.tick()
    assert client.sent_commands == []
    free[0] = True
    cues.tick()
    assert _kinds(client) == ["goto", "set_target"]


def test_breathe_is_withheld_when_muted_like_any_breathe():
    cues, machine, client, *_ = _rig(muted=True)
    machine.link_lost("x")
    cues.tick()
    assert _kinds(client) == ["goto"]  # settle only
