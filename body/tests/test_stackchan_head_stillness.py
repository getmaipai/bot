"""The head never moves on its own (owner request 2026-10-20: servo wear from constant movement)."""

from __future__ import annotations

import math

import pytest

from maipai_body.app import StackChanBehavior
from maipai_body.bodies.stackchan import StackChanRobotAdapter
from maipai_body.bodies.stackchan.estop_recovery import EstopRecovery
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.head_gate import HeadMotionGate
from maipai_body.hal.errors import BodyLost
from maipai_body.hal.seam import HeadPose


def _moves(device: FakeStackChanDeviceClient) -> int:
    return sum(c.name == "self.robot.set_head_angles" for c in device.calls)


@pytest.fixture
def behavior():
    device = FakeStackChanDeviceClient()
    b = StackChanBehavior(StackChanRobotAdapter(device).robot)
    b.device = device
    yield b
    b.close()


def test_a_fresh_unit_is_still_until_the_hub_says_otherwise(behavior):
    assert behavior.idle_level == "still"


@pytest.mark.parametrize("primitive", ["settle", "attend", "glance", "tilt", "perk"])
def test_no_ambient_move_when_the_robot_must_be_still(behavior, primitive):
    behavior.idle_still = lambda: True  # unknown power, charging, or level still
    assert behavior.render_primitive(primitive) is False
    assert _moves(behavior.device) == 0


def test_no_ambient_move_while_resting(behavior):
    behavior._rest = type("Rest", (), {"stage": "drowsy"})()
    assert behavior.render_primitive("settle") is False
    assert _moves(behavior.device) == 0


def test_the_settle_after_a_turn_runs_only_if_the_head_moved(behavior):
    behavior.render_turn_state("settle")
    behavior.render_turn_state("settle")
    assert _moves(behavior.device) == 0  # nothing moved, so nothing to bring back
    behavior.render_turn_state("listening")
    after_listen = _moves(behavior.device)
    assert after_listen > 0
    behavior.render_turn_state("settle")
    assert _moves(behavior.device) == after_listen + 1
    behavior.render_turn_state("settle")
    assert _moves(behavior.device) == after_listen + 1


def test_head_moves_are_capped_per_minute_even_for_answers():
    now = [0.0]
    gate = HeadMotionGate(must_be_still=lambda: False, clock=lambda: now[0], max_moves_per_min=3)
    assert [gate.allow("t", response=True) for _ in range(5)] == [True, True, True, False, False]
    now[0] = 61.0
    assert gate.allow("t", response=True) is True


def test_a_turn_cannot_move_the_head_past_the_cap(behavior):
    behavior.head_gate = HeadMotionGate(must_be_still=lambda: False, max_moves_per_min=2)
    for _ in range(6):
        behavior.render_turn_state("listening")
    assert _moves(behavior.device) <= 2


def test_recovery_backs_off_when_the_stop_keeps_coming_back():
    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    now = [0.0]
    recovery = EstopRecovery(robot, lambda: device.connected, clock=lambda: now[0])

    def latch() -> None:
        robot.lease.acquire("person", "estop-recovery")
        device.connected = False
        with pytest.raises(BodyLost):
            robot.head.goto(pose=HeadPose(pitch=math.radians(45)))
        device.connected = True

    def release() -> None:
        recovery.tick()
        now[0] += recovery.required_settle_s
        assert recovery.tick() is True

    latch()
    assert recovery.required_settle_s == 3.0
    release()
    now[0] += 5.0
    latch()
    recovery.tick()  # first look at the new latch counts the quick relatch
    assert recovery.required_settle_s == 6.0
    now[0] += 6.0
    assert recovery.tick() is True
    now[0] += 5.0
    latch()
    recovery.tick()
    assert recovery.required_settle_s == 12.0
    now[0] += 12.0
    assert recovery.tick() is True
    now[0] += 500.0  # a long quiet spell forgets the history
    latch()
    recovery.tick()
    assert recovery.required_settle_s == 3.0


def test_every_head_move_call_site_is_audited():
    # docs/dev/stackchan-head-motion-audit-2026-10-20.md lists why each one is safe.
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "maipai_body"
    found = {
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if "robot.head.set(" in path.read_text()
    }
    assert found == {
        "bodies/stackchan/adapter.py",
        "bodies/stackchan/renderer.py",
        "bodies/stackchan/routines.py",
        "selftest/stackchan_wiring.py",
    }
