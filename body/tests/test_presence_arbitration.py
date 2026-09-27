"""The arbitration priority: tracking outranks expression, yields to stop and service.

Design record section 6: "consented tracking sits below inhibit, reflex
and service, above expression and idle."
"""

from __future__ import annotations

from maipai_body.presence.arbitration import (
    ArbitrationPriority,
    ArbitrationState,
    active_priority,
    expression_may_drive,
    tracking_may_drive,
)


def test_nothing_active_is_idle():
    assert active_priority(ArbitrationState()) == ArbitrationPriority.IDLE


def test_tracking_alone_may_drive():
    state = ArbitrationState(tracking_active=True)
    assert tracking_may_drive(state) is True
    assert active_priority(state) == ArbitrationPriority.TRACKING


def test_tracking_outranks_expression():
    """Both want the head; tracking wins, expression is denied."""
    state = ArbitrationState(tracking_active=True, expression_active=True)
    assert tracking_may_drive(state) is True
    assert expression_may_drive(state) is False
    assert active_priority(state) == ArbitrationPriority.TRACKING


def test_expression_alone_may_drive():
    state = ArbitrationState(expression_active=True)
    assert expression_may_drive(state) is True


def test_stop_outranks_tracking():
    state = ArbitrationState(stop_active=True, tracking_active=True)
    assert tracking_may_drive(state) is False
    assert active_priority(state) == ArbitrationPriority.INHIBIT_REFLEX


def test_service_outranks_tracking():
    state = ArbitrationState(service_active=True, tracking_active=True)
    assert tracking_may_drive(state) is False
    assert active_priority(state) == ArbitrationPriority.SERVICE


def test_stop_outranks_everything():
    state = ArbitrationState(
        stop_active=True, service_active=True, tracking_active=True, expression_active=True
    )
    assert active_priority(state) == ArbitrationPriority.INHIBIT_REFLEX
    assert tracking_may_drive(state) is False
    assert expression_may_drive(state) is False
