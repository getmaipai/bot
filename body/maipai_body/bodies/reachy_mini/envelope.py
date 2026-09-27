"""The Reachy Mini envelope check, shared by the live client and the fake.

Kept out of `profile.py` so the numeric-limits test
(`tests/test_no_stray_limits.py`) has exactly one file to look at; this
module reads its limits from `PROFILE` and declares none of its own.
"""

from __future__ import annotations

import math

from maipai_body.hal.errors import OutOfEnvelope
from maipai_body.hal.seam import HeadPose

from .profile import PROFILE


def _angle_diff_deg(a_deg: float, b_deg: float) -> float:
    """The signed shortest angular difference `a - b`, in degrees."""
    a = math.radians(a_deg)
    b = math.radians(b_deg)
    return math.degrees(math.atan2(math.sin(a - b), math.cos(a - b)))


def check_envelope(
    pose: HeadPose | None,
    antennas: tuple[float, float] | None,
    body_yaw: float | None,
    effective_head_yaw: float,
    effective_body_yaw: float,
) -> None:
    """Raise `OutOfEnvelope` if a target falls outside `PROFILE`'s declared axes.

    The head-to-body delta check always runs, even on a command that sets
    only `body_yaw` (or only `antennas`): `effective_head_yaw` and
    `effective_body_yaw` are the caller's last known values, used whenever
    this command does not itself set one, so a body-yaw-only command
    cannot push the real delta past the limit unseen.
    """
    violations: list[str] = []

    def _axis_check(axis_name: str, value_deg: float) -> None:
        axis = PROFILE.axis(axis_name)
        if not (axis.min <= value_deg <= axis.max):
            violations.append(
                f"{axis_name}={value_deg:.2f}{axis.unit} outside [{axis.min}, {axis.max}]"
            )

    if pose is not None:
        _axis_check("head_pitch", math.degrees(pose.pitch))
        _axis_check("head_roll", math.degrees(pose.roll))
        _axis_check("head_yaw", math.degrees(pose.yaw))

    if antennas is not None:
        for value in antennas:
            _axis_check("antennas", math.degrees(value))

    if body_yaw is not None:
        _axis_check("body_yaw", math.degrees(body_yaw))

    head_yaw_deg = math.degrees(pose.yaw) if pose is not None else math.degrees(effective_head_yaw)
    body_yaw_deg = (
        math.degrees(body_yaw) if body_yaw is not None else math.degrees(effective_body_yaw)
    )
    delta = _angle_diff_deg(head_yaw_deg, body_yaw_deg)
    _axis_check("head_to_body_yaw_delta", delta)

    if violations:
        raise OutOfEnvelope("; ".join(violations))


def check_envelope_with_defaults(
    pose: HeadPose | None,
    antennas: tuple[float, float] | None,
    body_yaw: float | None,
    last_head_yaw: float,
    last_body_yaw: float,
) -> None:
    """`check_envelope`, filling in the head-to-body delta's two yaws.

    The one place both the live client and the fake compute "what yaw is
    this command effectively commanding" from a caller's last known
    values, so that logic exists once rather than copied in each.
    """
    effective_head_yaw = pose.yaw if pose is not None else last_head_yaw
    effective_body_yaw = body_yaw if body_yaw is not None else last_body_yaw
    check_envelope(pose, antennas, body_yaw, effective_head_yaw, effective_body_yaw)
