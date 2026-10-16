"""S-EXPR-04: DoA front/back disambiguation against a mirrored array fixture."""

from __future__ import annotations

import math

import pytest

from maipai_body.presence.doa import (
    BODY_LIMIT_RAD,
    DoaAction,
    DoaResolver,
    sdk_angle_to_bearing,
    wrap,
)

DEG = math.pi / 180.0


def mirrored_reading(source_world: float, body_yaw: float) -> float:
    """A linear array covers the front 180 degrees: a source behind reads as its mirror."""
    rel = wrap(source_world - body_yaw)
    if abs(rel) <= math.pi / 2:
        return rel
    return math.copysign(math.pi - abs(rel), rel)


def run_fixture(source_deg: float, *, face_bearing=None):
    """Drive the resolver against the fixture; return (facing, body_yaw, actions)."""
    source = source_deg * DEG
    resolver = DoaResolver()
    body = 0.0
    facing = 0.0
    actions = []
    now = 0.0
    for _ in range(12):
        decision = resolver.observe(
            now,
            bearing=mirrored_reading(source, body),
            body_yaw=body,
            face_bearing=face_bearing,
        )
        actions.append(decision.action)
        if decision.action in (DoaAction.PROBE, DoaAction.TURN):
            body = decision.body_yaw
            facing = decision.head_yaw
        elif decision.action == DoaAction.LOOK:
            facing = decision.head_yaw
        now += 0.7
        if decision.action in (DoaAction.LOOK, DoaAction.TURN):
            break
    return facing, body, actions


@pytest.mark.parametrize("source_deg", [110.0, 100.0, 115.0, -110.0, -115.0])
def test_a_source_behind_ends_with_the_body_facing_it(source_deg):
    facing, body, actions = run_fixture(source_deg)
    assert DoaAction.TURN in actions
    assert abs(body) <= BODY_LIMIT_RAD + 1e-9
    assert body == pytest.approx(source_deg * DEG, abs=2 * DEG)
    assert facing == pytest.approx(source_deg * DEG, abs=2 * DEG)


@pytest.mark.parametrize("source_deg", [80.0, 70.0, -85.0])
def test_a_real_side_source_is_confirmed_by_the_probe_and_looked_at(source_deg):
    facing, body, actions = run_fixture(source_deg)
    assert DoaAction.TURN not in actions
    assert actions[0] == DoaAction.PROBE and actions[-1] == DoaAction.LOOK
    assert facing == pytest.approx(source_deg * DEG, abs=2 * DEG)


def test_a_front_source_needs_no_probe():
    facing, body, actions = run_fixture(30.0)
    assert actions == [DoaAction.LOOK]
    assert body == 0.0
    assert facing == pytest.approx(30 * DEG)


def test_a_face_within_twenty_degrees_confirms_the_bearing_without_a_probe():
    resolver = DoaResolver()
    bearing = 85.0 * DEG
    decision = resolver.observe(0.0, bearing=bearing, body_yaw=0.0, face_bearing=75.0 * DEG)
    assert decision.action == DoaAction.LOOK
    assert not resolver.probing


def test_a_face_further_than_twenty_degrees_does_not_confirm():
    resolver = DoaResolver()
    decision = resolver.observe(0.0, bearing=85.0 * DEG, body_yaw=0.0, face_bearing=40.0 * DEG)
    assert decision.action == DoaAction.PROBE
    assert decision.body_yaw == pytest.approx(20.0 * DEG)
    assert decision.over_s == pytest.approx(0.6)


def test_samples_during_the_probe_turn_are_ignored():
    resolver = DoaResolver()
    resolver.observe(0.0, bearing=85.0 * DEG, body_yaw=0.0)
    assert resolver.observe(0.3, bearing=85.0 * DEG, body_yaw=0.35).action == DoaAction.NONE


def test_a_source_past_the_limit_is_clamped_to_the_body_limit():
    facing, body, _ = run_fixture(115.0)
    assert abs(body) <= BODY_LIMIT_RAD


def test_sdk_angle_conversion_puts_front_at_zero():
    assert sdk_angle_to_bearing(math.pi / 2) == pytest.approx(0.0)
    assert sdk_angle_to_bearing(0.0) == pytest.approx(math.pi / 2)  # left, positive
