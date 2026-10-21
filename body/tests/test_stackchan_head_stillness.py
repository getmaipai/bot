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
        "app.py",  # the spoken head command: an explicit request, see head_commands.py
        "bodies/stackchan/adapter.py",
        "bodies/stackchan/renderer.py",
        "bodies/stackchan/routines.py",
        "selftest/stackchan_wiring.py",
    }


def test_a_return_to_centre_passes_after_the_cap_is_used_up_and_is_not_counted():
    now = [0.0]
    gate = HeadMotionGate(must_be_still=lambda: False, clock=lambda: now[0], max_moves_per_min=3)
    assert [gate.allow("decorative", response=True) for _ in range(5)] == [True] * 3 + [False] * 2
    assert gate.allow("turn:settle", essential=True) is True
    assert gate.allow("turn:settle", essential=True) is True
    now[0] += 61.0
    assert [gate.allow("decorative", response=True) for _ in range(3)] == [True] * 3  # not used up


def test_essential_moves_pass_even_when_the_robot_must_be_still():
    gate = HeadMotionGate(must_be_still=lambda: True, resting=lambda: True)
    assert gate.allow("ambient:attend") is False
    assert gate.allow("turn:settle", essential=True) is True


def test_a_settle_still_centres_the_head_after_a_burst_of_decorative_moves(behavior):
    behavior.head_gate = HeadMotionGate(must_be_still=lambda: False, max_moves_per_min=2)
    for _ in range(5):
        behavior.render_turn_state("listening")
    before = _moves(behavior.device)
    assert before <= 2  # the cap held the decorative moves
    behavior.render_turn_state("settle")
    assert _moves(behavior.device) == before + 1  # the settle went through anyway


def test_only_states_that_move_the_head_count_toward_the_cap(behavior):
    gate = HeadMotionGate(must_be_still=lambda: False, max_moves_per_min=100)
    behavior.head_gate = gate
    for state in ("listening", "thinking", "reply_mood", "speaking", "settle"):
        behavior.render_turn_state(state)
    assert len(gate._recent) == 3  # listening, thinking, speaking; not reply_mood or settle


def _sleeping_behavior(events):
    from types import SimpleNamespace

    device = FakeStackChanDeviceClient()
    behavior = StackChanBehavior(StackChanRobotAdapter(device).robot)
    behavior._rest = type("Rest", (), {"stage": "asleep", "update": behavior._rest.update})()
    polls = []

    def poll():
        polls.append(1)
        return [SimpleNamespace(kind=kind) for kind in events.pop(0)] if events else []

    behavior.event_poll = poll
    return behavior, polls


def test_a_touch_wakes_a_sleeping_robot_after_the_first_look_empties_the_queue():
    behavior, polls = _sleeping_behavior(
        [["head_touch", "head_swipe_forward"], ["head_touch", "head_swipe_forward"]]
    )
    try:
        assert behavior.wake_on_touch(100.0) is False  # old events: drained, not a reason to wake
        assert behavior.wake_on_touch(101.0) is False  # polled too soon
        assert len(polls) == 1
        assert behavior.wake_on_touch(106.0) is True
        assert behavior._last_person_seen == 106.0
        assert behavior.wake_on_touch(112.0) is False  # nothing new
    finally:
        behavior.close()


def test_an_awake_robot_reads_events_slowly_and_keeps_reading_them_during_a_turn():
    behavior, polls = _sleeping_behavior([[], ["shake"], ["shake"]])
    seen = []
    try:
        behavior._rest = type("Rest", (), {"stage": "awake"})()
        behavior.reaction = seen.append
        assert behavior.wake_on_touch(0.0) is False  # first look: drains
        assert behavior.wake_on_touch(1.0) is False  # inside the 2 s interval
        assert behavior.wake_on_touch(2.5) is False  # awake: reacts but never "wakes"
        assert seen == [["shake"]] and len(polls) == 2
        behavior._active.set()
        assert behavior.wake_on_touch(10.0) is False
        assert len(polls) == 3  # events are read during a turn too, so no pat is lost
    finally:
        behavior.close()


def test_events_after_a_long_pause_are_old_and_only_drain():
    behavior, polls = _sleeping_behavior([["shake"], ["shake"]])
    seen = []
    try:
        behavior._rest = type("Rest", (), {"stage": "awake"})()
        behavior.reaction = seen.append
        behavior.wake_on_touch(0.0)  # drains
        behavior.wake_on_touch(100.0)  # 100 s later: that batch is old news
        assert seen == []
    finally:
        behavior.close()


def test_touch_wakes_have_a_cooldown():
    behavior, polls = _sleeping_behavior([[], ["shake"], ["shake"], ["shake"]])
    try:
        behavior.wake_on_touch(0.0)  # drain
        assert behavior.wake_on_touch(5.0) is True
        assert behavior.wake_on_touch(10.0) is False  # inside the 30 s cooldown
        assert behavior.wake_on_touch(40.0) is True
    finally:
        behavior.close()


def test_a_touch_wake_brings_the_rest_policy_back_to_awake():
    from types import SimpleNamespace

    device = FakeStackChanDeviceClient()
    behavior = StackChanBehavior(StackChanRobotAdapter(device).robot)
    try:
        behavior._rest._stage = "asleep"
        queue = [[], [SimpleNamespace(kind="head_touch"), SimpleNamespace(kind="head_swipe_back")]]
        behavior.event_poll = lambda: queue.pop(0) if queue else []
        now = 1000.0
        behavior.wake_on_touch(now)
        behavior.wake_on_touch(now + 5.0)
        assert behavior.rest_step(now + 5.0) == "awake"
    finally:
        behavior.close()


def test_screen_touch_diagnostics_are_logged_and_never_wake_or_react(caplog):
    import logging
    from types import SimpleNamespace

    behavior, _polls = _sleeping_behavior([])
    batch = [
        SimpleNamespace(kind="touch_down", extra={"x": 12, "y": 34}),
        SimpleNamespace(kind="gesture", extra={"dir": 8}),
    ]
    queue = [[], batch]
    behavior.event_poll = lambda: queue.pop(0) if queue else []
    seen = []
    behavior.reaction = seen.append
    try:
        behavior.wake_on_touch(0.0)  # drains
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            assert behavior.wake_on_touch(5.0) is False  # asleep, yet a diagnostic never wakes
        assert seen == []
        lines = [r.getMessage() for r in caplog.records if "unit touch" in r.getMessage()]
        assert lines == ["unit touch: touch_down x=12 y=34", "unit touch: gesture dir=8"]
    finally:
        behavior.close()
