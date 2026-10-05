"""RM-02: the primitive table's Reachy Mini column (``dev.md`` section 5).

Renders each primitive through the HAL seam's ``HeadActuator``, scaled
by ``REACHY_MINI_EXPRESSION_ENVELOPE``'s fractions of the profile's
declared axis limits. ``goto`` (minjerk) drives a fixed target and
duration; ``set_target`` drives the four primitives that own their own
continuous trajectory: track, breathe, speak, stop (RM-02's own words).

Each primitive is a list of ``Step``s so the deterministic tests can
inspect exactly what would be sent (``build_steps``) without needing a
client at all, and ``render`` is the one place that actually calls the
seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from maipai_body.bodies.reachy_mini.envelope import axis_bounds_rad
from maipai_body.hal.seam import AntennaPositions, BodyProfile, HeadActuator, HeadPose

from .envelope import REACHY_MINI_EXPRESSION_ENVELOPE, PrimitiveEnvelope
from .renderers import register_renderer

StepMethod = Literal["goto", "set_target", "hold"]


@dataclass
class Step:
    """One command this primitive issues to the HeadActuator."""

    method: StepMethod
    pose: HeadPose | None = None
    antennas: AntennaPositions | None = None
    body_yaw: float | None = None
    duration_s: float = 0.4


def _amplitude_rad(profile: BodyProfile, axis_name: str, fraction: float) -> float:
    """A fraction of the named axis's positive-side range, in radians."""
    if fraction == 0.0:
        return 0.0
    _, high = axis_bounds_rad(profile.axis(axis_name))
    return high * fraction


def _sign(value: float) -> float:
    return 1.0 if value >= 0.0 else -1.0


def build_steps(primitive: str, profile: BodyProfile, *, doa_angle_rad: float = 0.0) -> list[Step]:
    """The sequence of HeadActuator calls that renders ``primitive`` on this profile."""
    if primitive == "stop":
        return [Step(method="hold")]

    if primitive == "track":
        # A single deadbanded step toward the direction of arrival; EXPR-04's
        # own loop is what re-issues this continuously as the target moves.
        return [Step(method="set_target", pose=HeadPose(yaw=doa_angle_rad))]

    if primitive not in REACHY_MINI_EXPRESSION_ENVELOPE:
        raise ValueError(f"no Reachy Mini rendering declared for primitive {primitive!r}")
    spec: PrimitiveEnvelope = REACHY_MINI_EXPRESSION_ENVELOPE[primitive]
    yaw_sign = _sign(doa_angle_rad)

    if primitive == "listen":
        head_yaw = _amplitude_rad(profile, "head_yaw", spec.yaw_fraction) * yaw_sign
        return [
            Step(
                method="goto",
                pose=HeadPose(yaw=head_yaw),
                antennas=AntennaPositions(
                    left=_amplitude_rad(profile, "antenna_left", spec.antenna_fraction),
                    right=_amplitude_rad(profile, "antenna_right", spec.antenna_fraction),
                ),
                duration_s=spec.duration_s,
            )
        ]

    if primitive == "glance":
        left_amplitude = _amplitude_rad(profile, "antenna_left", spec.antenna_fraction)
        right_amplitude = _amplitude_rad(profile, "antenna_right", spec.antenna_fraction)
        left_antenna = left_amplitude if yaw_sign > 0 else 0.0
        right_antenna = -right_amplitude if yaw_sign < 0 else 0.0
        target = Step(
            method="goto",
            pose=HeadPose(
                yaw=_amplitude_rad(profile, "head_yaw", spec.yaw_fraction) * yaw_sign,
                roll=_amplitude_rad(profile, "head_roll", spec.roll_fraction) * yaw_sign,
            ),
            antennas=AntennaPositions(left=left_antenna, right=right_antenna),
            duration_s=spec.duration_s,
        )
        back = Step(
            method="goto",
            pose=HeadPose(),
            antennas=AntennaPositions(left=0.0, right=0.0),
            duration_s=spec.duration_s,
        )
        return [target, back]

    if primitive == "tilt":
        return [
            Step(
                method="goto",
                pose=HeadPose(
                    roll=_amplitude_rad(profile, "head_roll", spec.roll_fraction),
                    yaw=_amplitude_rad(profile, "head_yaw", spec.yaw_fraction),
                    pitch=-_amplitude_rad(profile, "head_pitch", spec.pitch_fraction),
                ),
                antennas=AntennaPositions(
                    left=_amplitude_rad(profile, "antenna_left", spec.antenna_fraction),
                    right=0.0,
                ),
                duration_s=spec.duration_s,
            )
        ]

    if primitive == "nod":
        dip = Step(
            method="goto",
            pose=HeadPose(pitch=_amplitude_rad(profile, "head_pitch", spec.pitch_fraction)),
            duration_s=spec.duration_s,
        )
        recover = Step(method="goto", pose=HeadPose(), duration_s=spec.duration_s)
        return [dip, recover]

    if primitive == "perk":
        return [
            Step(
                method="goto",
                pose=HeadPose(pitch=-_amplitude_rad(profile, "head_pitch", spec.pitch_fraction)),
                antennas=AntennaPositions(
                    left=_amplitude_rad(profile, "antenna_left", spec.antenna_fraction),
                    right=_amplitude_rad(profile, "antenna_right", spec.antenna_fraction),
                ),
                duration_s=spec.duration_s,
            )
        ]

    if primitive == "attend":
        return [
            Step(
                method="goto",
                pose=HeadPose(
                    pitch=_amplitude_rad(profile, "head_pitch", spec.pitch_fraction),
                    yaw=_amplitude_rad(profile, "head_yaw", spec.yaw_fraction) * yaw_sign,
                ),
                antennas=AntennaPositions(
                    left=-_amplitude_rad(profile, "antenna_left", spec.antenna_fraction),
                    right=-_amplitude_rad(profile, "antenna_right", spec.antenna_fraction),
                ),
                duration_s=spec.duration_s,
            )
        ]

    if primitive == "settle":
        return [
            Step(
                method="goto",
                pose=HeadPose(),
                antennas=AntennaPositions(left=0.0, right=0.0),
                duration_s=spec.duration_s,
            )
        ]

    if primitive == "breathe":
        left_amplitude = _amplitude_rad(profile, "antenna_left", spec.antenna_fraction)
        right_amplitude = _amplitude_rad(profile, "antenna_right", spec.antenna_fraction)
        return [
            Step(
                method="set_target",
                pose=HeadPose(
                    pitch=_amplitude_rad(profile, "head_pitch", spec.pitch_fraction),
                    roll=_amplitude_rad(profile, "head_roll", spec.roll_fraction),
                ),
                antennas=AntennaPositions(left=left_amplitude, right=-right_amplitude * 0.5),
            )
        ]

    if primitive == "muted":
        left_amplitude = _amplitude_rad(profile, "antenna_left", spec.antenna_fraction)
        right_amplitude = _amplitude_rad(profile, "antenna_right", spec.antenna_fraction)
        return [
            Step(
                method="goto",
                pose=HeadPose(),
                antennas=AntennaPositions(left=-left_amplitude, right=-right_amplitude),
                duration_s=spec.duration_s,
            )
        ]

    if primitive == "held":
        # Antennas only: the head holds through `stop` and the yaw is left alone.
        low = _amplitude_rad(profile, "antenna_left", spec.antenna_fraction)
        return [
            Step(
                method="goto",
                antennas=AntennaPositions(left=-low, right=-low),
                duration_s=spec.duration_s,
            )
        ]

    if primitive == "speak":
        left_amplitude = _amplitude_rad(profile, "antenna_left", spec.antenna_fraction)
        right_amplitude = _amplitude_rad(profile, "antenna_right", spec.antenna_fraction)
        return [
            Step(
                method="set_target",
                pose=HeadPose(pitch=_amplitude_rad(profile, "head_pitch", spec.pitch_fraction)),
                antennas=AntennaPositions(left=left_amplitude, right=right_amplitude),
            )
        ]

    raise ValueError(f"no renderer branch for primitive {primitive!r}")


def render(
    primitive: str, client: HeadActuator, profile: BodyProfile, *, doa_angle_rad: float = 0.0
) -> None:
    """Render one primitive on this profile, through the seam."""
    for step in build_steps(primitive, profile, doa_angle_rad=doa_angle_rad):
        if step.method == "hold":
            client.hold()
        elif step.method == "goto":
            client.goto(
                pose=step.pose,
                antennas=step.antennas,
                body_yaw=step.body_yaw,
                duration_s=step.duration_s,
                method="minjerk",
            )
        elif step.method == "set_target":
            client.set_target(pose=step.pose, antennas=step.antennas, body_yaw=step.body_yaw)


register_renderer("reachy_mini", render)
