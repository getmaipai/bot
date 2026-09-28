"""The calibrated envelope: fractions of the profile's declared axis limits.

RM-02's own words: "the envelope as fractions of the daemon's declared
limits written into device-scope settings with the run's date." No
settings store exists in this repo yet (that is Home's
``spec/settings``, RT-02 territory), so this module is that
declaration's stand-in, one dict, read by the renderer and nowhere
else. These are design defaults, not an owner's measured calibration
run (there is no unit yet): M-R2's simulator rows verify them against
the daemon's own limits, and a physical run replaces them once the
unit exists.
"""

from __future__ import annotations

from pydantic import BaseModel

_DEFAULT_SOURCE = (
    "design default pending M-R2's simulator measurement; not an owner "
    "calibration run (no physical unit yet)"
)
_DEFAULT_DATE = "2026-09-27"


class PrimitiveEnvelope(BaseModel):
    """One primitive's motion envelope: fractions of the profile's declared axis limits.

    A fraction of 0.0 means that axis does not move for this primitive.
    ``duration_s`` is the ``goto`` duration for primitives driven by
    ``goto`` (minjerk); primitives driven by ``set_target`` (track,
    breathe, speak, stop) ignore it.
    """

    pitch_fraction: float = 0.0
    roll_fraction: float = 0.0
    yaw_fraction: float = 0.0
    antenna_fraction: float = 0.0
    body_yaw_fraction: float = 0.0
    duration_s: float = 0.4
    source: str = _DEFAULT_SOURCE
    date: str = _DEFAULT_DATE


REACHY_MINI_EXPRESSION_ENVELOPE: dict[str, PrimitiveEnvelope] = {
    "listen": PrimitiveEnvelope(yaw_fraction=0.15, antenna_fraction=0.10, duration_s=0.3),
    "glance": PrimitiveEnvelope(
        yaw_fraction=0.25, roll_fraction=0.10, antenna_fraction=0.15, duration_s=0.25
    ),
    "tilt": PrimitiveEnvelope(
        roll_fraction=0.30,
        yaw_fraction=0.10,
        pitch_fraction=0.10,
        antenna_fraction=0.20,
        duration_s=0.4,
    ),
    "nod": PrimitiveEnvelope(pitch_fraction=0.20, duration_s=0.3),
    "perk": PrimitiveEnvelope(pitch_fraction=0.15, antenna_fraction=0.25, duration_s=0.2),
    "attend": PrimitiveEnvelope(
        pitch_fraction=0.08, yaw_fraction=0.08, antenna_fraction=0.08, duration_s=0.6
    ),
    "settle": PrimitiveEnvelope(duration_s=0.8),  # returns toward neutral; see renderer
    "breathe": PrimitiveEnvelope(pitch_fraction=0.03, roll_fraction=0.03, antenna_fraction=0.05),
    "speak": PrimitiveEnvelope(pitch_fraction=0.05, antenna_fraction=0.05),
    # Design record section 5's table: "muted (a state, not a cue) | neutral
    # | both fully down and still | none". A code review (2026-09-27) found
    # the first cut of this value (0.60) contradicted the safety rationale
    # its own comment cited: 2.4x to 6x every other primitive's antenna
    # fraction here, the opposite of section 7's "expression fractions stay
    # conservative ... no full-range excursions" (a rule that exists
    # specifically because this body has no near-hand sensor to freeze on).
    # 0.30 stays the most pronounced "down" in the table - clearly past
    # attend's subtle low (0.08) - without being an outlier against perk's
    # 0.25, tilt's 0.20, or glance's 0.15; a design default like every
    # other fraction here, for M-R2 to verify or correct.
    "muted": PrimitiveEnvelope(antenna_fraction=0.30, duration_s=0.5),
}
