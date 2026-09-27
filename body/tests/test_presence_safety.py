"""Tip and freefall from the IMU (design record section 7)."""

from __future__ import annotations

import math

from maipai_body.hal.seam import ImuReading
from maipai_body.presence.safety import is_freefall, is_tipped


def _imu(accelerometer=(0.0, 0.0, 9.81), quaternion=(1.0, 0.0, 0.0, 0.0)) -> ImuReading:
    return ImuReading(
        accelerometer=accelerometer,
        gyroscope=(0.0, 0.0, 0.0),
        quaternion=quaternion,
        temperature_c=25.0,
    )


def test_resting_upright_is_neither_tipped_nor_falling():
    reading = _imu()
    assert is_tipped(reading) is False
    assert is_freefall(reading) is False


def test_near_zero_acceleration_is_freefall():
    reading = _imu(accelerometer=(0.1, 0.0, 0.2))
    assert is_freefall(reading) is True


def test_a_small_tilt_is_not_tipped():
    """30 degrees about x: well under the 45-degree threshold."""
    half_angle = math.radians(30) / 2
    quaternion = (math.cos(half_angle), math.sin(half_angle), 0.0, 0.0)
    assert is_tipped(_imu(quaternion=quaternion)) is False


def test_a_90_degree_rotation_is_tipped():
    half_angle = math.radians(90) / 2
    quaternion = (math.cos(half_angle), math.sin(half_angle), 0.0, 0.0)
    assert is_tipped(_imu(quaternion=quaternion)) is True


def test_a_tilt_past_45_degrees_is_tipped():
    half_angle = math.radians(60) / 2
    quaternion = (math.cos(half_angle), math.sin(half_angle), 0.0, 0.0)
    assert is_tipped(_imu(quaternion=quaternion)) is True
