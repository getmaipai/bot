"""THERMAL-01: the Compute Module's temperature and throttle flags drive the body's load.

Rising order of the response (design record section 4, Reachy Mini only): vision
drops from 5 Hz to 2 Hz at 70 C, gestures suspend at 75 C, the idle level drops to
``still`` at 78 C. Each rung clears 3 C below where it set, so a reading wobbling at
a threshold does not flap. One clip line is said once per warm episode (from first
crossing 70 C until the module has cooled below the first rung's clear point). The
Eyes error look is for a real fault only: the firmware reporting it is throttling,
or the module at 85 C. The temperature and flag readers are the ones the budget
sampler already uses. Nothing here raises: an unreadable sensor keeps the last state.
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from maipai_body.measure.budget import (
    THERMAL_PATH,
    parse_thermal_millidegrees,
    parse_throttled,
)

logger = logging.getLogger("maipai_body.presence.thermal")

VISION_SLOW_C = 70.0
GESTURES_OFF_C = 75.0
IDLE_STILL_C = 78.0
FAULT_C = 85.0
HYSTERESIS_C = 3.0
VISION_FULL_HZ = 5.0
VISION_SLOW_HZ = 2.0

_RISE_C = (VISION_SLOW_C, GESTURES_OFF_C, IDLE_STILL_C)
_LEVEL_NAMES = ("nominal", "vision_slowed", "gestures_suspended", "idle_still")
# vcgencmd get_throttled, "now" bits that are the firmware cutting clocks for heat:
# 1 frequency capped, 2 throttled, 3 soft temperature limit. Bit 0 (under-voltage)
# is a power fact, not a thermal one.
_THROTTLED_NOW_MASK = 0b1110


@dataclass(frozen=True)
class ThermalState:
    temp_c: float | None = None
    level: int = 0
    throttled: bool = False
    fault: bool = False

    @property
    def name(self) -> str:
        return _LEVEL_NAMES[self.level]

    @property
    def vision_hz(self) -> float:
        return VISION_SLOW_HZ if self.level >= 1 else VISION_FULL_HZ

    @property
    def gestures_suspended(self) -> bool:
        return self.level >= 2

    @property
    def idle_still(self) -> bool:
        return self.level >= 3

    def as_frame(self) -> dict[str, Any]:
        """The value the state frame's ``thermal`` carries."""
        return {
            "level": self.name,
            "temp_c": self.temp_c,
            "vision_hz": self.vision_hz,
            "fault": self.fault,
        }


class ThermalGovernor:
    def __init__(self) -> None:
        self._state = ThermalState()
        self._line_owed = False

    @property
    def state(self) -> ThermalState:
        return self._state

    def update(self, temp_c: float | None, throttled_now: bool | None = None) -> ThermalState:
        if temp_c is None and throttled_now is None:
            return self._state
        previous = self._state
        temp = temp_c if temp_c is not None else previous.temp_c
        level = previous.level
        if temp is not None:
            while level < len(_RISE_C) and temp >= _RISE_C[level]:
                level += 1
            while level > 0 and temp < _RISE_C[level - 1] - HYSTERESIS_C:
                level -= 1
        throttled = previous.throttled if throttled_now is None else throttled_now
        fault_by_heat = temp is not None and (
            temp >= FAULT_C or (previous.fault and temp >= FAULT_C - HYSTERESIS_C)
        )
        if level >= 1 and previous.level == 0:
            self._line_owed = True
        elif level == 0:
            self._line_owed = False
        self._state = ThermalState(
            temp_c=temp, level=level, throttled=throttled, fault=throttled or fault_by_heat
        )
        return self._state

    def take_line(self) -> bool:
        """True once per warm episode, the first time it is asked after the episode began."""
        owed, self._line_owed = self._line_owed, False
        return owed


class Sampler(Protocol):
    def read(self) -> tuple[float | None, bool | None]: ...


def _read_text(path: str) -> str:
    return Path(path).read_text()


def _run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, timeout=2, check=True).stdout


class ThermalSampler:
    """The module's temperature and whether the firmware is throttling it right now."""

    def __init__(
        self,
        *,
        read_text: Callable[[str], str] = _read_text,
        run: Callable[[list[str]], str] = _run,
    ) -> None:
        self._read_text = read_text
        self._run = run

    def read(self) -> tuple[float | None, bool | None]:
        try:
            temp = parse_thermal_millidegrees(self._read_text(THERMAL_PATH))
        except (OSError, ValueError):
            temp = None
        try:
            raw = parse_throttled(self._run(["vcgencmd", "get_throttled"]))
        except (OSError, subprocess.SubprocessError):
            raw = None
        return temp, (None if raw is None else bool(raw & _THROTTLED_NOW_MASK))


class ThermalMonitor:
    """Samples at most every ``interval_s`` and feeds the governor; never raises."""

    def __init__(
        self,
        sampler: Sampler | None = None,
        *,
        governor: ThermalGovernor | None = None,
        clock: Callable[[], float] = time.monotonic,
        interval_s: float = 5.0,
    ) -> None:
        self._sampler = sampler or ThermalSampler()
        self.governor = governor or ThermalGovernor()
        self._clock = clock
        self._interval_s = interval_s
        self._next_at = float("-inf")

    @property
    def state(self) -> ThermalState:
        return self.governor.state

    def poll(self) -> ThermalState:
        now = self._clock()
        if now < self._next_at:
            return self.governor.state
        self._next_at = now + self._interval_s
        try:
            temp, throttled = self._sampler.read()
        except Exception:
            logger.warning("thermal sample failed", exc_info=True)
            return self.governor.state
        return self.governor.update(temp, throttled)

    def take_line(self) -> bool:
        return self.governor.take_line()
