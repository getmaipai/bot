"""The arbitration priority (``dev.md`` section 5, confirmed for this body by
the design record's section 6): "consented tracking sits below inhibit,
reflex and service, above expression and idle."

The bot backlog's RM-06 entry says the opposite ("tracking yields to
expression and stop"); the design record's own section 6, the section
RM-06 names as its source, states the order this module implements, so
that reading is taken as authoritative and recorded here rather than
guessed silently: tracking outranks expression, and only yields to a
stop (inhibit/reflex) or service condition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ArbitrationPriority(IntEnum):
    """Highest priority first (a lower number always wins)."""

    INHIBIT_REFLEX = 0
    SERVICE = 1
    TRACKING = 2
    EXPRESSION = 3
    IDLE = 4


@dataclass
class ArbitrationState:
    """What is currently asking to drive the head, this instant."""

    stop_active: bool = False
    service_active: bool = False
    tracking_active: bool = False
    expression_active: bool = False


def active_priority(state: ArbitrationState) -> ArbitrationPriority:
    """The single highest-priority thing asking to drive the head right now."""
    if state.stop_active:
        return ArbitrationPriority.INHIBIT_REFLEX
    if state.service_active:
        return ArbitrationPriority.SERVICE
    if state.tracking_active:
        return ArbitrationPriority.TRACKING
    if state.expression_active:
        return ArbitrationPriority.EXPRESSION
    return ArbitrationPriority.IDLE


def tracking_may_drive(state: ArbitrationState) -> bool:
    """True when tracking owns the head: nothing at or above its priority is active."""
    if state.stop_active or state.service_active:
        return False
    return state.tracking_active


def expression_may_drive(state: ArbitrationState) -> bool:
    """True when expression owns the head: nothing at or above its priority is active."""
    if state.stop_active or state.service_active or state.tracking_active:
        return False
    return state.expression_active
