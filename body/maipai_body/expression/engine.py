"""The expression engine: one cue in, one primitive rendered or withheld.

Ties ``map_cue_to_primitive``, ``suppression_reason`` and ``render``
together. A scripted cue source (bench testing) or, later, the
household runtime's real cue stream (EXPR-03) drives this the same way.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from maipai_body.hal.seam import BodyProfile, HeadActuator

from .cue import Cue, map_cue_to_primitive
from .renderers import renderer_for
from .suppression import SuppressionContext, suppression_reason


@dataclass
class ExpressionOutcome:
    """What the engine did with one cue: which primitive, or why it was withheld."""

    cue_seq: int
    primitive: str | None
    suppressed_reason: str | None
    rendered: bool
    # What actually reached the renderer, when it differs from `primitive`
    # (the muted pose standing in for a cue suppressed for being muted).
    # None when nothing rendered, or equal to `primitive` on a normal render.
    rendered_primitive: str | None = None


class ExpressionEngine:
    """Maps cues to primitives and renders them, honoring the suppression table.

    Looks up its render column from ``renderers.renderer_for(profile.id)``,
    never a hardcoded body's module, so a second body's own column is a
    registration, not an edit here.

    A ``threading.Lock`` serializes every render: the real client's own
    ``goto()`` blocks the calling thread until the daemon's task completes
    (the vendor SDK's ``goto_target`` calls ``wait_for_task_completion``
    before returning - verified in the installed ``reachy_mini`` package,
    not assumed), so two primitives cannot collide on a single calling
    thread today. The lock is what closes the gap once a second thread
    exists to call it from - EXPR-04's continuous idle/track/breathe loop
    running beside the turn-driven discrete cues this ``handle()`` already
    serves - so a `goto` in flight on one thread cannot be interleaved with
    a `set_target` from another. Full trajectory blending (merging two
    compatible small motions into one interpolated command, EXPR-01's
    other named gap) stays undesigned: there is no spec yet for what
    "compatible" means numerically, and guessing one would be exactly the
    kind of hand-built heuristic the org's standards ask to avoid.
    """

    def __init__(self, client: HeadActuator, profile: BodyProfile) -> None:
        self._client = client
        self._profile = profile
        self._render = renderer_for(profile.id)
        self._render_lock = threading.Lock()

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
            if reason == "muted":
                # dev.md's generic table only says muted suppresses this
                # primitive; the design record's own table (section 5) says
                # what that looks like on this body - antennas fully down,
                # not just frozen wherever they last were.
                with self._render_lock:
                    self._render("muted", self._client, self._profile)
                return ExpressionOutcome(
                    cue_seq=cue.cue_seq,
                    primitive=primitive,
                    suppressed_reason=reason,
                    rendered=True,
                    rendered_primitive="muted",
                )
            return ExpressionOutcome(
                cue_seq=cue.cue_seq, primitive=primitive, suppressed_reason=reason, rendered=False
            )

        direction = (
            cue.target_direction_rad if cue.target_direction_rad is not None else doa_angle_rad
        )
        with self._render_lock:
            self._render(primitive, self._client, self._profile, doa_angle_rad=direction)
        return ExpressionOutcome(
            cue_seq=cue.cue_seq,
            primitive=primitive,
            suppressed_reason=None,
            rendered=True,
            rendered_primitive=primitive,
        )
