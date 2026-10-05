"""MOVE-CARRY-01a: the deterministic motion state from scripted IMU readings.

Every reading comes from the S-FAKES-01 builders (``rest_reading``,
``tipped_reading``, ``freefall_reading``) or a small variation of them;
nothing here touches a body. The thresholds are UNMEASURED placeholders,
so the tests script values well clear of each one.
"""

from __future__ import annotations

from pathlib import Path

from maipai_body.bodies.reachy_mini.fake import (
    freefall_reading,
    rest_reading,
    tipped_reading,
)
from maipai_body.hal.seam import ImuReading
from maipai_body.presence import motion_state
from maipai_body.presence.motion_state import MotionState, MotionStateMachine

DT = 0.1
G = 9.81


def shaken(tick: int, amplitude: float = 3.0) -> ImuReading:
    """Proper acceleration swinging around 1 g, the way a hand moves the body."""
    z = G + amplitude * (1 if tick % 2 == 0 else -1)
    return ImuReading(
        accelerometer=(0.0, 0.0, z),
        gyroscope=(0.0, 0.0, 0.0),
        quaternion=(1.0, 0.0, 0.0, 0.0),
        temperature_c=30.0,
    )


class Run:
    """Feeds a machine at a fixed tick and keeps every state it reported."""

    def __init__(self) -> None:
        self.machine = MotionStateMachine()
        self.now = 0.0
        self.states: list[MotionState] = []

    def feed(self, reading: ImuReading, seconds: float) -> None:
        for tick in range(round(seconds / DT)):
            self.states.append(self.machine.update(reading, self.now))
            self.now += DT

    def shake(self, seconds: float) -> None:
        for tick in range(round(seconds / DT)):
            self.states.append(self.machine.update(shaken(tick), self.now))
            self.now += DT

    @property
    def last(self) -> MotionState:
        return self.states[-1]


def test_a_body_at_rest_stays_resting_and_never_puts_down():
    run = Run()
    run.feed(rest_reading(), 30.0)
    assert set(run.states) == {MotionState.RESTING}
    assert not run.machine.holding


def test_a_bump_is_never_carried():
    run = Run()
    run.feed(rest_reading(), 1.0)
    run.shake(0.2)
    run.feed(rest_reading(), 5.0)
    assert MotionState.BUMPED in run.states
    assert not {MotionState.LIFTED, MotionState.CARRIED, MotionState.PUT_DOWN} & set(run.states)
    assert run.last is MotionState.RESTING
    assert not run.machine.holding


def test_a_sustained_lift_is_lifted_then_carried():
    run = Run()
    run.feed(rest_reading(), 1.0)
    run.shake(0.8)
    assert run.last is MotionState.LIFTED
    assert run.machine.holding
    run.shake(2.0)
    assert run.last is MotionState.CARRIED
    assert run.machine.holding


def test_a_carry_is_never_freefall():
    run = Run()
    run.feed(rest_reading(), 1.0)
    run.shake(6.0)
    assert MotionState.CARRIED in run.states
    assert MotionState.FREEFALL not in run.states
    assert MotionState.TIPPED not in run.states


def test_put_down_follows_a_carry_after_the_stillness_window_once():
    run = Run()
    run.shake(4.0)
    assert run.last is MotionState.CARRIED
    run.feed(rest_reading(), motion_state.PUT_DOWN_STILL_S - 0.5)
    assert run.last is MotionState.CARRIED  # still inside the window
    assert run.machine.holding
    run.feed(rest_reading(), 1.0)
    assert MotionState.PUT_DOWN in run.states
    assert run.states.count(MotionState.PUT_DOWN) == 1
    assert run.last is MotionState.RESTING
    assert not run.machine.holding


def test_put_down_follows_a_lift_that_never_became_a_carry():
    run = Run()
    run.shake(0.8)
    assert run.last is MotionState.LIFTED
    run.feed(rest_reading(), motion_state.PUT_DOWN_STILL_S + 0.5)
    assert MotionState.CARRIED not in run.states
    assert MotionState.PUT_DOWN in run.states


def test_put_down_needs_a_lift_first():
    run = Run()
    run.feed(rest_reading(), 5.0)
    run.shake(0.2)  # a bump
    run.feed(rest_reading(), 10.0)
    assert MotionState.PUT_DOWN not in run.states


def test_a_drop_while_held_is_freefall_and_the_hold_stays_until_it_lands_and_rests():
    run = Run()
    run.shake(4.0)
    run.feed(freefall_reading(), 0.5)
    assert run.last is MotionState.FREEFALL
    assert run.machine.holding
    run.feed(rest_reading(), motion_state.PUT_DOWN_STILL_S + 0.5)
    assert run.last is MotionState.RESTING
    assert MotionState.PUT_DOWN in run.states
    assert not run.machine.holding


def test_a_tilt_past_45_degrees_while_held_is_tipped():
    run = Run()
    run.shake(4.0)
    run.feed(tipped_reading(0.9), 0.5)  # about 52 degrees
    assert run.last is MotionState.TIPPED
    assert run.machine.holding
    run.feed(tipped_reading(0.6), 0.5)  # about 34 degrees, held again
    assert run.last is MotionState.CARRIED


def test_a_tipped_body_is_never_put_down_while_it_lies_tipped():
    run = Run()
    run.shake(4.0)
    run.feed(tipped_reading(1.2), 10.0)
    assert set(run.states[-50:]) == {MotionState.TIPPED}
    assert MotionState.PUT_DOWN not in run.states
    assert run.machine.holding


def test_freefall_outranks_tipped_and_both_report_at_rest_without_a_hold():
    run = Run()
    run.feed(tipped_reading(1.2), 0.5)
    assert run.last is MotionState.TIPPED
    assert not run.machine.holding
    run.feed(freefall_reading(), 0.5)
    assert run.last is MotionState.FREEFALL
    assert not run.machine.holding  # a drop from a table is not a lift


def test_a_missing_reading_changes_nothing():
    run = Run()
    run.shake(4.0)
    before = run.last
    assert run.machine.update(None, run.now) is before
    assert run.machine.holding


def test_every_threshold_is_marked_unmeasured_and_the_runbook_has_a_unit_row():
    assert "UNMEASURED" in motion_state.THRESHOLD_STATUS
    runbook = Path(__file__).resolve().parents[2] / "docs" / "dev" / "measure-runbook.md"
    assert "MOVE-CARRY-01" in runbook.read_text()
