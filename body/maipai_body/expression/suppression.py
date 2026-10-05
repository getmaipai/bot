"""The suppression table (``dev.md`` section 5's "Suppressed or reinterpreted when" column).

``SuppressionContext`` carries every reason any body's primitives can be
suppressed for. A body with no sensor for a given reason (Reachy Mini has
no near-hand or dock sensor yet) simply never sets that field, which is
the honest state, not a stub: the machinery and its tests are real, the
body just cannot yet trigger every reason.
"""

from __future__ import annotations

from pydantic import BaseModel


class SuppressionContext(BaseModel):
    """The body's own safety and service state at the moment a primitive would render."""

    near_hand: bool = False
    service_mode: bool = False
    dock_transition: bool = False
    thermal_pressure: bool = False
    muted: bool = False
    stale_track: bool = False
    playfulness_forbidden: bool = False
    guard_forbidden: bool = False
    is_defer: bool = False
    is_safety_line: bool = False
    tool_failure: bool = False
    no_fresh_target: bool = False
    held: bool = False


def suppression_reason(primitive: str, context: SuppressionContext) -> str | None:
    """Return why ``primitive`` is suppressed right now, or ``None`` if it may render.

    ``stop`` is never suppressed by anything (dev.md section 5's own
    words); every other primitive checks only the reasons its own row
    names.
    """
    if primitive == "stop":
        return None

    # MOVE-CARRY-01: lifted or carried, the body commands no motion at all.
    if context.held:
        return "held"

    if primitive == "listen":
        if context.muted:
            return "muted"
        return None

    if primitive == "glance":
        if context.no_fresh_target:
            return "no_fresh_target"
        return None

    if primitive == "nod":
        if context.guard_forbidden:
            return "guard_forbidden"
        if context.is_defer:
            return "defer"
        if context.is_safety_line:
            return "safety_line"
        if context.tool_failure:
            return "tool_failure"
        return None

    if primitive == "perk":
        if context.playfulness_forbidden:
            return "playfulness_forbidden"
        return None

    if primitive == "breathe":
        if context.near_hand:
            return "near_hand"
        if context.service_mode:
            return "service_mode"
        if context.dock_transition:
            return "dock_transition"
        if context.thermal_pressure:
            return "thermal_pressure"
        if context.muted:
            return "muted"
        return None

    if primitive == "track":
        if context.stale_track:
            return "stale_track"
        return None

    return None
