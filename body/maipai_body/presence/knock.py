"""KNOCK-01: a double knock on the body, read from the IMU.

A knock is a short accelerometer transient: the proper acceleration leaves
1 g by more than ``KNOCK_ACCEL_M_S2`` and the body is quiet again within
``MAX_IMPULSE_S``. Two knocks at least ``MIN_SPACING_S`` apart and inside
``DOUBLE_WINDOW_S`` make a double knock, reported once.

Anything longer than an impulse is not a knock: a lift or a carry keeps the
body moving for far more than ``MAX_IMPULSE_S``, which blocks the detector
until the body has been quiet for ``QUIET_S``. The caller also passes
``suppressed`` (held, or the robot is moving), which clears every pending
knock. No learned component. Thresholds are UNMEASURED design defaults with
a unit row in ``docs/dev/measure-runbook.md``; the mic onset detector
(2 kHz high-pass, spectral flux) is the second candidate if the IMU read
rate proves too coarse.
"""

from __future__ import annotations

import math

from maipai_body.hal.seam import ImuReading

from .motion_state import GRAVITY_M_S2, is_moving

THRESHOLD_STATUS = (
    "UNMEASURED design defaults; the unit row is KNOCK-01 in docs/dev/measure-runbook.md."
)

# A transient this far from 1 g counts as a knock candidate.
KNOCK_ACCEL_M_S2 = 2.5
# The body must be quiet again within this long, or the event is movement, not a knock.
MAX_IMPULSE_S = 0.12
# Two knocks closer than this are one knock (ring-down); the second must come inside the window.
MIN_SPACING_S = 0.2
DOUBLE_WINDOW_S = 1.0
# Quiet needed to clear the block a long movement set.
QUIET_S = 0.3


class KnockDetector:
    """Feed it each IMU reading with a monotonic time in seconds."""

    def __init__(self) -> None:
        self._run_start: float | None = None
        self._run_has_transient = False
        self._blocked = False
        self._quiet_since: float | None = None
        self._knocks: list[float] = []

    def reset(self) -> None:
        self.__init__()

    def update(self, reading: ImuReading | None, now_s: float, *, suppressed: bool = False) -> bool:
        """True exactly once per completed double knock."""
        if reading is None:
            return False
        if suppressed:
            self.reset()
            self._blocked = True  # the first quiet window after a suppression unblocks
            return False
        ax, ay, az = reading.accelerometer
        deviation = abs(math.sqrt(ax * ax + ay * ay + az * az) - GRAVITY_M_S2)
        moving = is_moving(reading)

        if moving:
            self._quiet_since = None
            if self._run_start is None:
                self._run_start = now_s
                self._run_has_transient = False
            if deviation > KNOCK_ACCEL_M_S2:
                self._run_has_transient = True
            if now_s - self._run_start > MAX_IMPULSE_S:
                self._blocked = True
                self._knocks.clear()
            return False

        # Quiet sample.
        if self._quiet_since is None:
            self._quiet_since = now_s
        if self._blocked and now_s - self._quiet_since >= QUIET_S:
            self._blocked = False
        if self._run_start is None:
            return False
        start, transient = self._run_start, self._run_has_transient
        self._run_start = None
        if self._blocked or not transient:
            return False
        return self._register(start)

    def _register(self, at_s: float) -> bool:
        if self._knocks and at_s - self._knocks[-1] < MIN_SPACING_S:
            return False  # ring-down of the knock already counted
        if self._knocks and at_s - self._knocks[-1] > DOUBLE_WINDOW_S:
            self._knocks.clear()
        self._knocks.append(at_s)
        if len(self._knocks) < 2:
            return False
        self._knocks.clear()
        return True
