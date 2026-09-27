"""The typed cue and the phase-to-primitive mapping (``dev.md`` section 5).

``Cue`` is a local stand-in for the engine's own ``ExpressionCue``, which
does not exist yet (WIRE-01/EXPR-03 wait on the household runtime).  Its
fields are the subset of the signal that ``dev.md``'s primitive table
actually reads (``primary_act``, ``expressed_emotion``,
``emotion_intensity``, whether a real target is present, whether
``react`` is allowed, ``repair``, and the guard-replacement flag on
``speak``), so the same mapping logic in ``map_cue_to_primitive`` is the
one EXPR-03 replaces with the real signal, not reimplements.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class Phase(StrEnum):
    """A turn's cue points (``dev.md`` section 5's own inventory)."""

    HEARD = "heard"
    SIGNAL = "signal"
    RESIGNAL = "resignal"
    PLAN = "plan"
    OUTCOME = "outcome"
    SPEAK = "speak"
    DONE = "done"
    CANCEL = "cancel"


class Cue(BaseModel):
    """One point in a turn where the primitive table's trigger column reads a signal."""

    phase: Phase
    cue_seq: int
    primary_act: str | None = None
    expressed_emotion: str | None = None
    emotion_intensity: str | None = None
    has_target: bool = False
    target_direction_rad: float | None = None
    react_allowed: bool = True
    is_safety_line: bool = False
    is_confirmation_ask: bool = False
    outcome_ok: bool | None = None
    replaced: bool = False


def map_cue_to_primitive(cue: Cue) -> str | None:
    """Return the primitive name this cue selects, or ``None`` for no primitive.

    A first cut of ``dev.md`` section 5's trigger column: EXPR-03 (after
    the real engine exists) refines this against the actual
    ``TurnSignal``/``ReplyPlan`` fields; this proves the same mapping
    shape against a scripted source (EXPR-01's own acceptance).
    """
    if cue.phase is Phase.HEARD:
        return "listen"

    if cue.phase in (Phase.SIGNAL, Phase.RESIGNAL):
        if cue.primary_act in ("question", "ask_back"):
            if cue.is_safety_line or cue.is_confirmation_ask:
                return None
            return "tilt"
        if cue.expressed_emotion == "happiness" and cue.emotion_intensity in (
            "moderate",
            "high",
        ):
            if not cue.react_allowed:
                return None
            return "perk"
        if cue.expressed_emotion in ("sadness", "fear"):
            return "attend"
        if cue.primary_act == "care":
            return "attend"
        if cue.has_target and cue.react_allowed:
            return "glance"
        if cue.primary_act == "inform" and cue.react_allowed:
            return "nod"
        return None

    if cue.phase is Phase.OUTCOME:
        if cue.outcome_ok:
            return "nod"
        return None

    if cue.phase is Phase.SPEAK:
        if cue.replaced:
            return None  # a guard replacement withholds the nod, never the sway
        return "speak"

    if cue.phase is Phase.DONE:
        return "settle"

    if cue.phase is Phase.CANCEL:
        return "stop"

    return None  # PLAN: the plan-driven half waits on ACT-03 (out of scope)
