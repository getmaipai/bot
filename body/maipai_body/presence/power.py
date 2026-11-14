"""SELF-SCENE-02: the battery and heat ladder, kept by the body with no hub.

Battery rungs (percent, falling): *warn* at ``robot.power.warn_at`` (default 20),
*degrade* at 15, *dock* at 10, *sleep* at 5. Each rung rises when the level is at or
below it and falls only 3 points above it, so a reading wobbling at a threshold does
not flap. Each rung's line is said at most once per discharge: the body keeps that
counter itself and only charging resets it (a level that wobbles back over a rung
without a charger never earns a second line). Charging clears every state.

* warn: one short line, only if someone is near; nobody near means nothing, and the
  rung is spent.
* degrade: head moves, the look and breathing off, the screen dim. Nothing spoken.
* dock: "Could someone put me on my charger?" once.
* sleep: a goodbye, a 5 second grace, the safe pose, sleep. This is the one line that
  plays through quiet hours; every other line here waits for them to end.

Heat rungs (degrees C, rising): warm 70, hot 76, critical 82, each clearing 3 C
lower. Critical stops motion and says one line per episode.

Lines come in two pools. A child (or an unknown person, who might be one) gets the
child pool: soft wording, never a percentage and never the words fault, critical or
error. Nothing here reads a face; the audience comes from the presence entries the
body already keeps.

Nothing here raises. An unreadable battery or temperature keeps the last state, and
the firmware's failed-read zero (0 percent, not charging) is unknown, not empty
(the ``light_wiring`` precedent).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import IntEnum, StrEnum

from maipai_body.settings_keys import DEFAULT_POWER_WARN_AT

HYSTERESIS_PERCENT = 3
DEGRADE_AT = 15
DOCK_AT = 10
SLEEP_AT = 5
GOODBYE_GRACE_S = 5.0  # docs/dev.md power defaults: the 5 s goodbye grace

WARM_C = 70.0
HOT_C = 76.0
CRITICAL_C = 82.0
HEAT_HYSTERESIS_C = 3.0


class PowerLevel(IntEnum):
    OK = 0
    WARN = 1
    DEGRADED = 2
    DOCK = 3
    SLEEP = 4


class HeatLevel(IntEnum):
    NOMINAL = 0
    WARM = 1
    HOT = 2
    CRITICAL = 3


class Rung(StrEnum):
    """A spoken rung: the ``line.power.*`` family and the heat line."""

    WARN = "warn"
    DOCK = "dock"
    GOODBYE = "goodbye"
    HEAT = "heat"


_BATTERY_LINE_RUNGS = {
    PowerLevel.WARN: Rung.WARN,
    PowerLevel.DOCK: Rung.DOCK,
    PowerLevel.SLEEP: Rung.GOODBYE,
}

# Fixed-line pool ids (variants are `<id>.1`, `<id>.2` in offline_clips.json).
LINE_IDS: Mapping[tuple[Rung, bool], str] = {
    (Rung.WARN, False): "line.power.warn",
    (Rung.WARN, True): "line.power.warn_child",
    (Rung.DOCK, False): "line.power.dock",
    (Rung.DOCK, True): "line.power.dock_child",
    (Rung.GOODBYE, False): "line.power.goodbye",
    (Rung.GOODBYE, True): "line.power.goodbye_child",
    (Rung.HEAT, False): "line.power.heat",
    (Rung.HEAT, True): "line.power.heat_child",
}


def line_id(rung: Rung, *, child: bool) -> str:
    return LINE_IDS[(rung, child)]


def child_pool(kinds: Sequence[str] | None) -> bool:
    """True when the child pool applies: anyone present is a child or not known to be
    anything else. With no presence information the adult pool is used."""
    if not kinds:
        return False
    return any(kind in ("child", "unknown") for kind in kinds)


def clamp_warn_at(value: int) -> int:
    """The warn rung stays above the degrade rung and at or below 50."""
    return max(DEGRADE_AT + 1, min(50, value))


class PowerLadder:
    """Battery state machine over (percent, charging) samples."""

    def __init__(self, warn_at: int = DEFAULT_POWER_WARN_AT) -> None:
        self._warn_at = clamp_warn_at(warn_at)
        self.level = PowerLevel.OK
        self.percent: int | None = None
        self.charging: bool | None = None
        self._spent: set[PowerLevel] = set()  # rungs whose line was earned this discharge
        self._owed: PowerLevel | None = None
        self._sleep_at: float | None = None

    def set_warn_at(self, warn_at: int) -> None:
        self._warn_at = clamp_warn_at(warn_at)

    @property
    def low_power(self) -> bool:
        """The state frame's flag: the body is in its reduced mode (degrade or beyond)."""
        return self.level >= PowerLevel.DEGRADED

    def _threshold(self, level: PowerLevel) -> int:
        return {
            PowerLevel.WARN: self._warn_at,
            PowerLevel.DEGRADED: DEGRADE_AT,
            PowerLevel.DOCK: DOCK_AT,
            PowerLevel.SLEEP: SLEEP_AT,
        }[level]

    def update(self, percent: int | None, charging: bool | None, now: float) -> PowerLevel:
        if percent is not None and not (percent == 0 and not charging):
            self.percent = max(0, min(100, int(percent)))
        if charging is not None:
            self.charging = charging
        if charging is True:
            self._clear()
            return self.level
        if self.percent is None:
            return self.level
        previous = self.level
        level = previous
        while level < PowerLevel.SLEEP and self.percent <= self._threshold(PowerLevel(level + 1)):
            level = PowerLevel(level + 1)
        while level > PowerLevel.OK and self.percent >= self._threshold(level) + HYSTERESIS_PERCENT:
            level = PowerLevel(level - 1)
        self.level = level
        if level > previous:
            self._on_rise(level, now)
        elif level < PowerLevel.SLEEP:
            self._sleep_at = None
        return level

    def _clear(self) -> None:
        self.level = PowerLevel.OK
        self._spent.clear()
        self._owed = None
        self._sleep_at = None

    def _on_rise(self, level: PowerLevel, now: float) -> None:
        if level == PowerLevel.SLEEP and self._sleep_at is None:
            self._sleep_at = now
        # A rung crossed past an unsaid lower rung makes that line stale.
        if self._owed is not None and self._owed < level:
            self._owed = None
        if level in _BATTERY_LINE_RUNGS and level not in self._spent:
            self._spent.add(level)
            self._owed = level

    def line_owed(self) -> Rung | None:
        return None if self._owed is None else _BATTERY_LINE_RUNGS[self._owed]

    def take_line(self, *, near: bool, quiet: bool, may_speak: bool) -> Rung | None:
        """The rung to say now, once, or None.

        ``may_speak`` is false while a turn runs or the robot is muted: the line stays
        owed. Quiet hours hold every line but the goodbye (the dock ask waits for
        them to end if the battery is still at that rung). The warn line is spent the
        moment it is considered with nobody near, or in quiet hours."""
        owed = self._owed
        if owed is None or not may_speak:
            return None
        rung = _BATTERY_LINE_RUNGS[owed]
        if rung is Rung.GOODBYE:
            self._owed = None
            return rung
        if quiet:
            if rung is Rung.WARN:
                self._owed = None
            return None
        self._owed = None
        if rung is Rung.WARN and not near:
            return None
        return rung

    def forgo_line(self) -> None:
        """Drop a line still owed (the goodbye must not play after the body is asleep)."""
        self._owed = None

    def sleep_due(self, now: float) -> bool:
        """True from the end of the goodbye grace until charging clears the state."""
        return self._sleep_at is not None and now - self._sleep_at >= GOODBYE_GRACE_S


class HeatLadder:
    """Temperature state machine: warm 70, hot 76, critical 82, 3 C hysteresis."""

    _RISE = (WARM_C, HOT_C, CRITICAL_C)

    def __init__(self) -> None:
        self.level = HeatLevel.NOMINAL
        self.temp_c: float | None = None
        self._owed = False

    @property
    def motion_stopped(self) -> bool:
        return self.level >= HeatLevel.CRITICAL

    def update(self, temp_c: float | None) -> HeatLevel:
        if temp_c is None:
            return self.level
        self.temp_c = temp_c
        previous = self.level
        level = int(previous)
        while level < len(self._RISE) and temp_c >= self._RISE[level]:
            level += 1
        while level > 0 and temp_c < self._RISE[level - 1] - HEAT_HYSTERESIS_C:
            level -= 1
        self.level = HeatLevel(level)
        if self.level >= HeatLevel.CRITICAL and previous < HeatLevel.CRITICAL:
            self._owed = True
        elif self.level < HeatLevel.CRITICAL:
            self._owed = False
        return self.level

    def take_line(self, *, quiet: bool, may_speak: bool) -> Rung | None:
        """One line per critical episode; quiet hours and a running turn defer it."""
        if not self._owed or quiet or not may_speak:
            return None
        self._owed = False
        return Rung.HEAT
