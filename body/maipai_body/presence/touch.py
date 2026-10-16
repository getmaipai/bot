"""Antenna touch detection from commanded and observed positions.

Thresholds are design defaults pending the T0 to T4 unit experiments in
``docs/dev/measure-runbook.md``.  This module emits an observation only;
callers may map it to acknowledge or wake, never to offer acceptance.
"""

from __future__ import annotations

from dataclasses import dataclass

from maipai_body.hal.seam import AntennaPositions

DEVIATION_RAD = 0.4
REARM_RAD = 0.1
HOLD_SAMPLES = 3
REFRACTORY_S = 0.25
DRIVE_SUPPRESSION_S = 0.260


@dataclass(frozen=True)
class TouchEvent:
    """One acknowledged antenna push, with the side that moved."""

    side: str
    at_s: float


class AntennaTouchDetector:
    """Debounce antenna displacement while respecting expression ownership."""

    def __init__(self) -> None:
        self._active = False
        self._over_count = 0
        self._last_event_s = float("-inf")
        self._drive_until_s = float("-inf")
        self._side: str | None = None

    def note_drive(self, now_s: float, *, driving: bool) -> None:
        """Suppress readings during antenna motion and for 260 ms afterwards."""
        if driving:
            self._drive_until_s = max(self._drive_until_s, now_s + DRIVE_SUPPRESSION_S)

    def update(
        self,
        commanded: AntennaPositions,
        present: AntennaPositions,
        *,
        now_s: float,
        driving: bool = False,
        offer_active: bool = False,
    ) -> TouchEvent | None:
        """Return a touch observation, never an offer acceptance signal."""
        self.note_drive(now_s, driving=driving)
        left = abs(present.left - commanded.left)
        right = abs(present.right - commanded.right)
        deviation = max(left, right)
        side = "left" if left >= right else "right"

        if deviation < REARM_RAD:
            self._active = False
            self._over_count = 0
            self._side = None
            return None
        if driving or now_s < self._drive_until_s:
            self._over_count = 0
            return None
        if self._active:
            return None
        if deviation <= DEVIATION_RAD:
            self._over_count = 0
            self._side = None
            return None
        if now_s - self._last_event_s < REFRACTORY_S:
            return None
        if self._side != side:
            self._side = side
            self._over_count = 0
        self._over_count += 1
        if self._over_count < HOLD_SAMPLES:
            return None

        self._active = True
        self._over_count = 0
        self._last_event_s = now_s
        # offer_active is intentionally not used to accept anything. Keep
        # the observation available to acknowledge/wake consumers only.
        _ = offer_active
        return TouchEvent(side=side, at_s=now_s)
