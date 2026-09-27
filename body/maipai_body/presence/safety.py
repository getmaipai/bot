"""Tip and freefall from the IMU (design record section 7: "From the IMU: motors
disabled, one line spoken, the body reports the event").

No numeric threshold is named anywhere for this body (the MaiPai
build's own thresholds, where they exist, are hardware-specific and do
not apply here); these are design defaults pending a physical run on
the unit, the same honest framing ``expression/envelope.py`` already
uses, never a claimed, validated safety limit.
"""

from __future__ import annotations

import math

from maipai_body.hal.seam import ImuReading

_DEFAULT_SOURCE = "design default pending a physical run on the unit; not a validated limit"
_DEFAULT_DATE = "2026-09-27"

# Free fall reads near-zero proper acceleration; resting gravity is ~9.81 m/s^2.
FREEFALL_ACCELERATION_THRESHOLD_M_S2 = 2.0

# More than 45 degrees from upright.
TIP_UPRIGHT_COSINE_THRESHOLD = math.cos(math.radians(45))


def is_freefall(reading: ImuReading) -> bool:
    """True when the accelerometer reads near-zero proper acceleration."""
    ax, ay, az = reading.accelerometer
    magnitude = math.sqrt(ax * ax + ay * ay + az * az)
    return magnitude < FREEFALL_ACCELERATION_THRESHOLD_M_S2


def is_tipped(reading: ImuReading) -> bool:
    """True when the body's own up axis has rotated more than 45 degrees from upright.

    ``quaternion`` is ``(w, x, y, z)`` (``reachy_mini.io.protocol``'s own
    documented order); ``1 - 2*(x^2 + y^2)`` is the z-component of the
    rotated local z-axis in the world frame for a unit quaternion in that
    order, 1.0 when upright and 0.0 at exactly 90 degrees.
    """
    _w, x, y, z = reading.quaternion
    upright_z = 1.0 - 2.0 * (x * x + y * y)
    return upright_z < TIP_UPRIGHT_COSINE_THRESHOLD
