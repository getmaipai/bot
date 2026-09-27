"""The suppression table (dev.md section 5's "Suppressed or reinterpreted when" column)."""

from __future__ import annotations

from maipai_body.expression.suppression import SuppressionContext, suppression_reason


def test_stop_is_never_suppressed():
    context = SuppressionContext(
        near_hand=True,
        service_mode=True,
        dock_transition=True,
        thermal_pressure=True,
        muted=True,
        stale_track=True,
        playfulness_forbidden=True,
        guard_forbidden=True,
        is_defer=True,
        is_safety_line=True,
        tool_failure=True,
        no_fresh_target=True,
    )
    assert suppression_reason("stop", context) is None


def test_listen_is_suppressed_when_muted():
    assert suppression_reason("listen", SuppressionContext(muted=True)) == "muted"


def test_listen_renders_when_not_muted():
    assert suppression_reason("listen", SuppressionContext()) is None


def test_glance_is_suppressed_with_no_fresh_target():
    context = SuppressionContext(no_fresh_target=True)
    assert suppression_reason("glance", context) == "no_fresh_target"


def test_nod_is_suppressed_when_the_guards_forbid_it():
    assert suppression_reason("nod", SuppressionContext(guard_forbidden=True)) == "guard_forbidden"


def test_nod_is_suppressed_on_defer():
    assert suppression_reason("nod", SuppressionContext(is_defer=True)) == "defer"


def test_nod_is_suppressed_on_a_safety_line():
    assert suppression_reason("nod", SuppressionContext(is_safety_line=True)) == "safety_line"


def test_nod_is_suppressed_on_a_tool_failure():
    assert suppression_reason("nod", SuppressionContext(tool_failure=True)) == "tool_failure"


def test_perk_is_suppressed_when_playfulness_is_forbidden():
    context = SuppressionContext(playfulness_forbidden=True)
    assert suppression_reason("perk", context) == "playfulness_forbidden"


def test_breathe_is_suppressed_by_each_of_its_named_reasons():
    assert suppression_reason("breathe", SuppressionContext(near_hand=True)) == "near_hand"
    assert suppression_reason("breathe", SuppressionContext(service_mode=True)) == "service_mode"
    assert (
        suppression_reason("breathe", SuppressionContext(dock_transition=True)) == "dock_transition"
    )
    assert (
        suppression_reason("breathe", SuppressionContext(thermal_pressure=True))
        == "thermal_pressure"
    )
    assert suppression_reason("breathe", SuppressionContext(muted=True)) == "muted"


def test_track_is_suppressed_on_a_stale_track():
    assert suppression_reason("track", SuppressionContext(stale_track=True)) == "stale_track"


def test_an_unlisted_primitive_condition_never_suppresses():
    """settle, attend, tilt and speak name no suppression reason in dev.md's table."""
    context = SuppressionContext(
        near_hand=True, service_mode=True, muted=True, stale_track=True, guard_forbidden=True
    )
    for primitive in ("settle", "attend", "tilt", "speak"):
        assert suppression_reason(primitive, context) is None
