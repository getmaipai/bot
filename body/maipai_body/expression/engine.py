"""The expression engine: one cue in, one primitive rendered or withheld.

Ties ``map_cue_to_primitive``, ``suppression_reason`` and ``render``
together. A scripted cue source (bench testing) or, later, the
household runtime's real cue stream (EXPR-03) drives this the same way.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from maipai_body.hal.seam import BodyProfile, HeadActuator
from maipai_body.presence.arbitration import ArbitrationState, expression_may_drive

from .cue import Cue, map_cue_to_primitive
from .primitives import HELD_STATE, MUTED_STATE, PRIMITIVE_NAMES
from .renderers import renderer_for
from .suppression import SuppressionContext, suppression_reason


@dataclass
class ExpressionOutcome:
    """What the engine did with one cue: which primitive, or why it was withheld."""

    cue_seq: int
    primitive: str | None
    suppressed_reason: str | None
    rendered: bool
    # What actually reached the renderer. None when nothing rendered
    # (`primitive` is None, or the cue was suppressed), equal to
    # `primitive` on a normal render, or a set_muted() outcome's own
    # rendered_primitive ("muted" or "settle") when cue_seq is -1.
    rendered_primitive: str | None = None


class ExpressionEngine:
    """Maps cues to primitives and renders them, honoring the suppression table.

    Looks up its render column from ``renderers.renderer_for(profile.id)``,
    never a hardcoded body's module, so a second body's own column is a
    registration, not an edit here.

    A ``threading.Lock`` serializes every render except ``stop``: the real
    client's own ``goto()`` blocks the calling thread until the daemon's
    task completes (the vendor SDK's ``goto_target`` calls
    ``wait_for_task_completion`` before returning - verified in the
    installed ``reachy_mini`` package, not assumed), so two primitives
    cannot collide on a single calling thread today. The lock is what
    closes the gap once a second thread exists to call it from - EXPR-04's
    continuous idle/track/breathe loop running beside the turn-driven
    discrete cues this ``handle()`` already serves - so a `goto` in flight
    on one thread cannot be interleaved with a `set_target` from another.
    ``stop`` bypasses the lock (a code review, 2026-09-27, found the lock
    otherwise makes `stop` wait behind whatever is already in flight,
    inverting the one priority `dev.md` makes absolute) and is issued
    immediately regardless of what else is rendering. Full trajectory
    blending (merging two compatible small motions into one interpolated
    command, EXPR-01's other named gap) stays undesigned: there is no spec
    yet for what "compatible" means numerically, and guessing one would be
    exactly the kind of hand-built heuristic the org's standards ask to
    avoid.
    """

    def __init__(self, client: HeadActuator, profile: BodyProfile) -> None:
        self._client = client
        self._profile = profile
        self._render = renderer_for(profile.id)
        self._render_lock = threading.Lock()
        self._muted = False

    def handle(
        self, cue: Cue, context: SuppressionContext, *, doa_angle_rad: float = 0.0
    ) -> ExpressionOutcome:
        """Render the cue's primitive, or report why it did not render.

        ``doa_angle_rad`` is the array's live direction-of-arrival reading
        (for primitives that orient toward whoever is speaking now, such
        as listen, attend and track); a cue that names its own
        ``target_direction_rad`` (a plan's real physical target, glance's
        own trigger) takes precedence over it.
        """
        primitive = map_cue_to_primitive(cue)
        if primitive is None:
            return ExpressionOutcome(
                cue_seq=cue.cue_seq, primitive=None, suppressed_reason=None, rendered=False
            )

        reason = suppression_reason(primitive, context)
        if reason is not None:
            # Plain "rendered=False", exactly as dev.md's generic table
            # says - `muted` is a state, not a cue-driven primitive
            # (primitives.py's own contract), so it is never rendered from
            # here; see set_muted() for the mute contract's own edge-driven
            # render, gated by arbitration.
            return ExpressionOutcome(
                cue_seq=cue.cue_seq, primitive=primitive, suppressed_reason=reason, rendered=False
            )

        direction = (
            cue.target_direction_rad if cue.target_direction_rad is not None else doa_angle_rad
        )
        self._render_named(primitive, direction)
        return ExpressionOutcome(
            cue_seq=cue.cue_seq,
            primitive=primitive,
            suppressed_reason=None,
            rendered=True,
            rendered_primitive=primitive,
        )

    def render_primitive(
        self,
        primitive: str,
        context: SuppressionContext,
        *,
        doa_angle_rad: float = 0.0,
        target_direction_rad: float | None = None,
        cue_seq: int = -1,
    ) -> ExpressionOutcome:
        """Render a named primitive through this engine's suppression and lock rules.

        Use this for explicit primitive controls that have no cue mapping,
        such as the dashboard's ``breathe`` and ``track`` buttons.
        """
        if primitive not in PRIMITIVE_NAMES:
            raise ValueError(f"unknown expression primitive {primitive!r}")
        reason = suppression_reason(primitive, context)
        if reason is not None:
            return ExpressionOutcome(
                cue_seq=cue_seq,
                primitive=primitive,
                suppressed_reason=reason,
                rendered=False,
            )
        direction = target_direction_rad if target_direction_rad is not None else doa_angle_rad
        self._render_named(primitive, direction)
        return ExpressionOutcome(
            cue_seq=cue_seq,
            primitive=primitive,
            suppressed_reason=None,
            rendered=True,
            rendered_primitive=primitive,
        )

    def _render_named(self, primitive: str, direction: float) -> None:
        """Serialize a body-column render, except stop which has absolute priority."""
        if primitive == "stop":
            # A code review (2026-09-27) found the render lock inverts
            # `stop`'s absolute priority (suppression.py: "stop is never
            # suppressed") the moment a second thread exists: a `goto` in
            # flight on one thread blocks for its whole duration (the
            # vendor SDK's own `wait_for_task_completion`), so a `stop`
            # handled on another thread would wait behind it before its
            # own `hold()` even reached the wire. `stop` bypasses the lock
            # so it is always issued immediately; `hold()` itself now sends
            # the daemon's own StopMoveCmd before re-holding the present
            # pose (client.py), so it actually cancels the in-flight motion
            # rather than losing a race with it. This does not help a
            # `stop` cue arriving on the SAME thread as a blocking goto -
            # that needs gotos issued from a worker the engine never
            # blocks on, EXPR-04's shape, not a lock change.
            self._render(primitive, self._client, self._profile, doa_angle_rad=direction)
        else:
            with self._render_lock:
                self._render(primitive, self._client, self._profile, doa_angle_rad=direction)

    def render_ambient(self, primitive: str, context: SuppressionContext) -> ExpressionOutcome:
        """Render a primitive named by a body state (the offline ladder's
        rung 0), not by a turn's cue. Same suppression table and render
        lock as :meth:`handle`; arbitration is the caller's to check."""
        reason = suppression_reason(primitive, context)
        if reason is not None:
            return ExpressionOutcome(
                cue_seq=-1, primitive=primitive, suppressed_reason=reason, rendered=False
            )
        with self._render_lock:
            self._render(primitive, self._client, self._profile)
        return ExpressionOutcome(
            cue_seq=-1,
            primitive=primitive,
            suppressed_reason=None,
            rendered=True,
            rendered_primitive=primitive,
        )

    def render_held_look(self) -> ExpressionOutcome:
        """MOVE-CARRY-01c: the antennas go once to the held pose. A state, not a
        cue, so the held suppression does not apply; the caller owns the gating
        (the setting, the mute, one render per lift)."""
        with self._render_lock:
            self._render(HELD_STATE, self._client, self._profile)
        return ExpressionOutcome(
            cue_seq=-1,
            primitive=None,
            suppressed_reason=None,
            rendered=True,
            rendered_primitive=HELD_STATE,
        )

    def set_muted(self, muted: bool, arbitration: ArbitrationState) -> ExpressionOutcome | None:
        """The mute contract's own entry point - a state change, not a cue.

        Edge-triggered: renders the muted pose once when ``muted`` turns
        true and ``settle`` once when it turns back false, each gated by
        ``expression_may_drive()`` so a mute during an active turn or
        under `stop`/service doesn't fight whatever the daemon's own
        tracker or a higher-priority render currently owns the head. A
        call with no edge (``muted`` unchanged) does nothing and returns
        ``None`` - idempotent, so a caller may report the mute state on
        every tick without re-rendering.

        A code review (2026-09-27) found the edge was consumed even when
        arbitration deferred the render: muting during tracking updated
        ``self._muted`` regardless, so once tracking ended there was no
        edge left to render the pose from, and the robot showed no
        visual mute for as long as anything higher-priority happened to
        be active at the exact moment mute was requested. ``self._muted``
        now only updates once a render actually happens, so a deferred
        edge stays pending and a later call with the same ``muted``
        value (the docstring's own "every tick") keeps retrying until
        arbitration allows it.
        """
        if muted == self._muted:
            return None
        if not expression_may_drive(arbitration):
            return None
        self._muted = muted
        primitive = MUTED_STATE if muted else "settle"
        with self._render_lock:
            self._render(primitive, self._client, self._profile)
        return ExpressionOutcome(
            cue_seq=-1,
            primitive=None,
            suppressed_reason=None,
            rendered=True,
            rendered_primitive=primitive,
        )
