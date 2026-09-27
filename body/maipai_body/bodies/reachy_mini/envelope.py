"""Shared envelope clamping for the Reachy Mini profile's real client and fake.

Both ``client.ReachyMiniClient`` and ``fake.FakeReachyMiniClient`` clamp
targets against ``profile.py``'s axes with this one set of checks, so the
same test suite proves the same promise, "raises OutOfEnvelope before
anything reaches the daemon", against both.
"""

from __future__ import annotations

import math

from maipai_body.hal.errors import OutOfEnvelope
from maipai_body.hal.seam import AntennaPositions, AxisLimit, BodyProfile, HeadPose


def axis_bounds_rad(axis: AxisLimit) -> tuple[float, float]:
    """Convert a profile axis's declared bound to radians for comparison."""
    if axis.unit == "deg":
        return math.radians(axis.min), math.radians(axis.max)
    if axis.unit == "rad":
        return axis.min, axis.max
    raise OutOfEnvelope(f"axis {axis.name!r} has no angular unit ({axis.unit!r})")


def clamp_angle(profile: BodyProfile, axis_name: str, value: float) -> None:
    """Raise OutOfEnvelope if ``value`` (radians) falls outside the named axis."""
    axis = profile.axis(axis_name)
    low, high = axis_bounds_rad(axis)
    if not (low <= value <= high):
        raise OutOfEnvelope(
            f"{axis_name} target {value:.4f} rad is outside "
            f"[{low:.4f}, {high:.4f}] rad ({axis.source}, {axis.date})"
        )


def clamp_target(
    profile: BodyProfile,
    pose: HeadPose | None,
    antennas: AntennaPositions | None,
    body_yaw: float | None,
) -> None:
    """Raise OutOfEnvelope on the first axis a target violates; check every axis touched."""
    if pose is not None:
        clamp_angle(profile, "head_pitch", pose.pitch)
        clamp_angle(profile, "head_roll", pose.roll)
        clamp_angle(profile, "head_yaw", pose.yaw)
    if antennas is not None:
        clamp_angle(profile, "antenna_left", antennas.left)
        clamp_angle(profile, "antenna_right", antennas.right)
    if body_yaw is not None:
        clamp_angle(profile, "body_yaw", body_yaw)
    head_yaw = pose.yaw if pose is not None else None
    if head_yaw is not None and body_yaw is not None:
        clamp_angle(profile, "head_to_body_yaw_delta", head_yaw - body_yaw)
