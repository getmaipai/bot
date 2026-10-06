"""The expression engine: one cue in, one primitive rendered or withheld.

Ties ``map_cue_to_primitive``, ``suppression_reason`` and ``render``
together. A scripted cue source (bench testing) or, later, the
household runtime's real cue stream (EXPR-03) drives this the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from maipai_body.hal.seam import (
    AntennaPositions,
    BodyProfile,
    HeadActuator,
    HeadPose,
    StateFeed,
)
from maipai_body.presence.arbitration import ArbitrationState, expression_may_drive

from .cue import Cue, Phase, map_cue_to_primitive
from .motion_worker import MotionLayer, MotionTarget, MotionWorker, entry_blend_seconds
from .primitives import HELD_STATE, MUTED_STATE, PRIMITIVE_NAMES
from .reachy_mini_renderer import build_steps
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

    A single motion worker owns actuator writes. Cues enqueue per-axis
    targets; the worker applies arbitration, blending, rate and acceleration
    limits, filtering, and profile bounds at 50 Hz. ``stop`` remains an
    immediate hold request so it can interrupt a running trajectory.
    """

    def __init__(
        self,
        client: HeadActuator,
        profile: BodyProfile,
        *,
        threaded: bool = False,
        speech_rms_provider: Callable[[], float] | None = None,
        initial_target: MotionTarget | None = None,
        state_feed_factory: Callable[[], StateFeed] | None = None,
    ) -> None:
        self._threaded = threaded
        self._client = client
        self._profile = profile
        self._worker = MotionWorker(
            client,
            profile,
            threaded=threaded,
            speech_rms_provider=speech_rms_provider,
            initial_target=initial_target,
            state_feed_factory=state_feed_factory,
        )
        self._muted = False
        self._last_cue_seq = -1
        self._turn_terminal = False

    @property
    def dropped_cues(self) -> int:
        return self._worker.dropped_cues

    def close(self) -> None:
        self._worker.close()

    def set_speech_rms(self, rms: float) -> None:
        self._worker.set_speech_rms(rms)

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
        if cue.cue_seq <= self._last_cue_seq or (
            self._turn_terminal and cue.phase is not Phase.HEARD
        ):
            self._worker.drop_stale_target()
            return ExpressionOutcome(
                cue_seq=cue.cue_seq,
                primitive=None,
                suppressed_reason="out_of_sequence",
                rendered=False,
            )
        self._last_cue_seq = cue.cue_seq
        if cue.phase is Phase.HEARD:
            self._turn_terminal = False
        elif cue.phase in (Phase.DONE, Phase.CANCEL):
            self._turn_terminal = True
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
        """Queue targets on the expression layer; stop bypasses blending."""
        if primitive == "stop":
            self._worker.stop()
            return
        sequence = []
        previous = self._worker.last_target
        for step in build_steps(primitive, self._profile, doa_angle_rad=direction):
            target = MotionTarget(
                pose=step.pose or HeadPose(),
                antennas=step.antennas or AntennaPositions(left=0.0, right=0.0),
                body_yaw=step.body_yaw or 0.0,
                owned_axes=frozenset(
                    (["head_pitch", "head_roll", "head_yaw"] if step.pose is not None else [])
                    + (["antenna_left", "antenna_right"] if step.antennas is not None else [])
                    + (["body_yaw"] if step.body_yaw is not None else [])
                ),
            )
            sequence.append((target, entry_blend_seconds(previous, target)))
            previous = target
        self._worker.submit_sequence(MotionLayer.EXPRESSION, sequence)
        if not self._worker.running:
            self._worker.flush()
            if primitive == "settle":
                self._worker.set_layer(
                    MotionLayer.EXPRESSION,
                    pose=HeadPose(),
                    antennas=AntennaPositions(left=0.0, right=0.0),
                    duration_s=0.0,
                )
                self._worker.tick(self._worker._clock() + 0.02)

    def render_ambient(self, primitive: str, context: SuppressionContext) -> ExpressionOutcome:
        """Render a body-state primitive through the worker."""
        reason = suppression_reason(primitive, context)
        if reason is not None:
            return ExpressionOutcome(
                cue_seq=-1, primitive=primitive, suppressed_reason=reason, rendered=False
            )
        self._render_named(primitive, 0.0)
        return ExpressionOutcome(
            cue_seq=-1,
            primitive=primitive,
            suppressed_reason=None,
            rendered=True,
            rendered_primitive=primitive,
        )

    def render_held_look(self) -> ExpressionOutcome:
        """MOVE-CARRY-01c: request the held pose on the expression layer."""
        self._render_named(HELD_STATE, 0.0)
        return ExpressionOutcome(
            cue_seq=-1,
            primitive=None,
            suppressed_reason=None,
            rendered=True,
            rendered_primitive=HELD_STATE,
        )

    def set_muted(self, muted: bool, arbitration: ArbitrationState) -> ExpressionOutcome | None:
        """Render the software-mute state on an allowed edge."""
        if muted == self._muted or not expression_may_drive(arbitration):
            return None
        primitive = MUTED_STATE if muted else "settle"
        self._render_named(primitive, 0.0)
        self._muted = muted
        return ExpressionOutcome(
            cue_seq=-1,
            primitive=None,
            suppressed_reason=None,
            rendered=True,
            rendered_primitive=primitive,
        )
