"""Idle: breathing, antenna sway and micro-poses (S-EXPR-04, design v2 section 4.3).

Pure and clock-injected like ``gaze``. ``IdlePolicy.update`` returns the
idle layer's target, or ``None`` while it must stay quiet. The policy only
ever returns a pose and antenna angles: it has no way to emit a clip, a
line or an offer, which is the acceptance rule "the idle loop never emits
a clip, line or offer" made structural.

All numbers are design defaults, UNMEASURED. ``robot.idle.level`` (declared
by SETTINGS-ROBOT-01) arrives through ``level_provider``:

* ``still``: breathe only.
* ``calm`` (default): breathe, antenna sway, micro-poses every 3 to 6 s.
* ``lively``: micro-poses twice as often, antenna sway 12 degrees.

The once-a-minute breathe while asleep is ``ExpressionEngine.sleep_breathe``
(the sleep pose owns the expression layer, so it is not an idle behaviour).
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

IdleLevel = Literal["still", "calm", "lively"]

_DEG = math.radians(1)

BREATHE_AMPLITUDE_RAD = 1.5 * _DEG
BREATHE_PITCH_PERIOD_S = 8.0
BREATHE_ROLL_PERIOD_S = 11.0
SWAY_FREQUENCY_HZ = 0.5
SWAY_PHASE_RAD = 1.3  # a third phase, unrelated to the two breathe periods
SWAY_CALM_RAD = 8.0 * _DEG
SWAY_LIVELY_RAD = 12.0 * _DEG
START_AFTER_MOVE_S = 0.3
MICRO_INTERVAL_S = (3.0, 6.0)
MICRO_YAW_RAD = 0.25
MICRO_PITCH_RAD = 0.11
SPEECH_FREEZE_DEBOUNCE_S = 0.15
SPEECH_UNFREEZE_S = 0.4
SOUND_LOOK_MIN_GAP_S = 60.0


@dataclass(frozen=True)
class IdleOutput:
    """Idle's target: head pitch/roll/yaw in radians and the two antenna angles."""

    pitch: float
    roll: float
    yaw: float
    antenna_left: float
    antenna_right: float


class IdlePolicy:
    """Decide what the head and antennas do when nothing else is asking."""

    def __init__(
        self,
        *,
        now: float,
        level_provider: Callable[[], IdleLevel] = lambda: "calm",
        rng: random.Random | None = None,
    ) -> None:
        self._level_provider = level_provider
        self._rng = rng or random.Random(0)
        self._origin = now
        self._last_move = now - START_AFTER_MOVE_S
        self._next_micro: float | None = None
        self._micro = (0.0, 0.0)  # (yaw, pitch)
        self._speech_since: float | None = None
        self._quiet_since: float | None = now
        self._frozen_antennas: tuple[float, float] | None = None
        self._last_sound_look = -1e9

    def notify_move(self, now: float) -> None:
        """A non-idle layer just moved the robot; idle waits 0.3 s before resuming."""
        self._last_move = now
        self._origin = now

    def sound_look(self, now: float, *, bearing: float) -> float | None:
        """A slow look toward a non-speech sound: a head yaw, at most once a minute."""
        if now - self._last_sound_look < SOUND_LOOK_MIN_GAP_S:
            return None
        self._last_sound_look = now
        return max(-MICRO_YAW_RAD * 2.0, min(MICRO_YAW_RAD * 2.0, bearing))

    def update(self, now: float, *, person_present: bool, user_speaking: bool) -> IdleOutput | None:
        if now - self._last_move < START_AFTER_MOVE_S:
            return None
        level = self._level_provider()
        t = now - self._origin
        pitch = BREATHE_AMPLITUDE_RAD * math.sin(2.0 * math.pi * t / BREATHE_PITCH_PERIOD_S)
        roll = BREATHE_AMPLITUDE_RAD * math.sin(2.0 * math.pi * t / BREATHE_ROLL_PERIOD_S)

        yaw = 0.0
        if level != "still" and person_present:
            yaw, micro_pitch = self._micro_pose(now, level)
            pitch += micro_pitch
        else:
            self._next_micro = None
            self._micro = (0.0, 0.0)

        left = right = 0.0
        if level != "still":
            amplitude = SWAY_LIVELY_RAD if level == "lively" else SWAY_CALM_RAD
            sway = amplitude * math.sin(2.0 * math.pi * SWAY_FREQUENCY_HZ * t + SWAY_PHASE_RAD)
            left, right = sway, -sway
            left, right = self._apply_speech_freeze(now, user_speaking, (left, right))
        return IdleOutput(pitch, roll, yaw, left, right)

    def _micro_pose(self, now: float, level: IdleLevel) -> tuple[float, float]:
        if self._next_micro is None:
            self._next_micro = now + self._interval(level)
        if now >= self._next_micro:
            self._micro = (
                self._rng.uniform(-MICRO_YAW_RAD, MICRO_YAW_RAD),
                self._rng.uniform(-MICRO_PITCH_RAD, MICRO_PITCH_RAD),
            )
            self._next_micro = now + self._interval(level)
        return self._micro

    def _interval(self, level: IdleLevel) -> float:
        low, high = MICRO_INTERVAL_S
        interval = self._rng.uniform(low, high)
        return interval / 2.0 if level == "lively" else interval

    def _apply_speech_freeze(
        self, now: float, speaking: bool, sway: tuple[float, float]
    ) -> tuple[float, float]:
        """Freeze the antennas 0.15 s into user speech, release 0.4 s after it ends."""
        if speaking:
            self._quiet_since = None
            if self._speech_since is None:
                self._speech_since = now
            if self._frozen_antennas is None and now - self._speech_since >= (
                SPEECH_FREEZE_DEBOUNCE_S
            ):
                self._frozen_antennas = sway
        else:
            self._speech_since = None
            if self._quiet_since is None:
                self._quiet_since = now
            if self._frozen_antennas is not None and now - self._quiet_since >= SPEECH_UNFREEZE_S:
                self._frozen_antennas = None
        return self._frozen_antennas if self._frozen_antennas is not None else sway
