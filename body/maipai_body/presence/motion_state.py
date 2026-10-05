"""MOVE-CARRY-01a: lifted, carried and put down, read from the IMU.

A deterministic state machine over the readings the body already takes
(``Imu.read``); reachy-mini 1.11.0 reports no lift or carry event, only
raw accelerometer, gyroscope and the fused quaternion. No learned
component: every transition is a threshold and a duration.

``tipped`` and ``freefall`` are RM-06's own observations
(``safety.is_tipped``, ``safety.is_freefall``, read here and never
changed) and outrank every other state. While the body is held, a drop
reads ``freefall`` and a tilt past 45 degrees reads ``tipped``, but the
hold itself stays latched: the body is not put down until it is moving no
more, upright and not falling. A drop from a table with no hold ahead of
it is ``freefall`` and nothing else.

Known limit: a body held perfectly still reads as put down after the
stillness window. A hand's own tremor sits well above the quiet
thresholds, which the unit row in ``docs/dev/measure-runbook.md`` checks.
"""

from __future__ import annotations

import math
from enum import StrEnum

from maipai_body.hal.seam import ImuReading

from .safety import is_freefall, is_tipped

THRESHOLD_STATUS = (
    "UNMEASURED design defaults, chosen well clear of a resting reading and a tabletop "
    "nudge; never a validated limit. The unit row is MOVE-CARRY-01 in "
    "docs/dev/measure-runbook.md."
)

GRAVITY_M_S2 = 9.81

# Proper acceleration this far from 1 g, or a rotation this fast, counts as moving.
MOVING_ACCELERATION_DEVIATION_M_S2 = 1.0
MOVING_GYRO_RAD_S = 0.4

# Moving for less than this is a bump, for at least this a lift.
LIFT_MIN_S = 0.4

# Total moving time while held that turns a lift into a carry.
CARRY_MOVING_S = 1.5

# Quiet for this long after a hold is a put down.
PUT_DOWN_STILL_S = 2.0

# How long a bump is reported before the state returns to resting.
BUMP_REPORT_S = 0.5


class MotionState(StrEnum):
    RESTING = "resting"
    BUMPED = "bumped"
    LIFTED = "lifted"
    CARRIED = "carried"
    PUT_DOWN = "put_down"
    TIPPED = "tipped"
    FREEFALL = "freefall"


def is_moving(reading: ImuReading) -> bool:
    ax, ay, az = reading.accelerometer
    deviation = abs(math.sqrt(ax * ax + ay * ay + az * az) - GRAVITY_M_S2)
    gx, gy, gz = reading.gyroscope
    rotation = math.sqrt(gx * gx + gy * gy + gz * gz)
    return deviation > MOVING_ACCELERATION_DEVIATION_M_S2 or rotation > MOVING_GYRO_RAD_S


class MotionStateMachine:
    """Feed it each IMU reading with a monotonic time in seconds."""

    def __init__(self) -> None:
        self._state = MotionState.RESTING
        self._holding = False
        self._carried = False
        self._burst_start: float | None = None
        self._bump_until = 0.0
        self._last: float | None = None
        self._moving_total_s = 0.0
        self._quiet_since: float | None = None

    @property
    def state(self) -> MotionState:
        return self._state

    @property
    def holding(self) -> bool:
        """True from the lift until the put down: lifted, carried, or held through a
        tip or a drop. The body commands no motion while this is true."""
        return self._holding

    def update(self, reading: ImuReading | None, now_s: float) -> MotionState:
        """One reading in, the state out. A missing reading changes nothing."""
        if reading is None:
            return self._state
        dt = 0.0 if self._last is None else max(0.0, now_s - self._last)
        self._last = now_s

        override = (
            MotionState.FREEFALL
            if is_freefall(reading)
            else MotionState.TIPPED
            if is_tipped(reading)
            else None
        )
        moving = is_moving(reading)

        if self._state is MotionState.PUT_DOWN:
            self._state = MotionState.RESTING

        if self._holding:
            self._update_held(moving, override, dt, now_s)
        else:
            self._update_free(moving, override, now_s)

        if override is not None:
            return override
        return self._state

    def _update_free(self, moving: bool, override: MotionState | None, now_s: float) -> None:
        if override is not None:
            # A fall or a topple with no lift ahead of it is not a lift.
            self._burst_start = None
            return
        if moving:
            if self._burst_start is None:
                self._burst_start = now_s
            if now_s - self._burst_start >= LIFT_MIN_S:
                self._holding = True
                self._carried = False
                self._moving_total_s = now_s - self._burst_start
                self._quiet_since = None
                self._burst_start = None
                self._state = MotionState.LIFTED
            return
        if self._burst_start is not None:
            self._burst_start = None
            self._state = MotionState.BUMPED
            self._bump_until = now_s + BUMP_REPORT_S
            return
        if self._state is MotionState.BUMPED and now_s >= self._bump_until:
            self._state = MotionState.RESTING

    def _update_held(
        self, moving: bool, override: MotionState | None, dt: float, now_s: float
    ) -> None:
        if moving:
            self._quiet_since = None
            self._moving_total_s += dt
            if self._moving_total_s >= CARRY_MOVING_S:
                self._carried = True
        elif self._quiet_since is None:
            self._quiet_since = now_s
        self._state = MotionState.CARRIED if self._carried else MotionState.LIFTED
        if (
            override is None
            and self._quiet_since is not None
            and now_s - self._quiet_since >= PUT_DOWN_STILL_S
        ):
            self._holding = False
            self._carried = False
            self._quiet_since = None
            self._moving_total_s = 0.0
            self._state = MotionState.PUT_DOWN
