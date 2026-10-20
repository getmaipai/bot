"""Rest: drowsy, asleep and waking routines so an idle StackChan never sits
smiling with its head up for hours (BOT-SC-ANIM-01, design v2 section 4.3).

Pure and clock-injected like ``idle``. ``RestPolicy.update`` returns the
rest layer's target for the current stage: a head drop fraction and a face.
Falling asleep is slow (idle timers count quiet seconds), waking is instant
(any activity resets the timer and returns to the awake stage at once).

All numbers are design defaults, UNMEASURED. ``quiet_hours_active`` halves
the drowsy and asleep thresholds when it returns true. ``turn_active``
counts as activity, so no stage change can happen while a turn is on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

RestStage = Literal["awake", "drowsy", "asleep"]
RestFace = Literal["neutral", "sleepy"]

DROWSY_AFTER_S = 600.0
ASLEEP_AFTER_S = 1800.0
QUIET_HOURS_FACTOR = 0.5
WAKE_SOUND_LEVEL = 0.5

PITCH_FRACTION: dict[RestStage, float] = {"awake": 0.0, "drowsy": 0.25, "asleep": 0.6}
FACE_BY_STAGE: dict[RestStage, RestFace] = {
    "awake": "neutral",
    "drowsy": "sleepy",
    "asleep": "sleepy",
}


@dataclass(frozen=True)
class RestOutput:
    """Rest's target: stage, head drop fraction (0..1 of the head's down range) and face."""

    stage: RestStage
    pose_pitch_fraction: float
    face: RestFace
    wake_transition: bool = False


class RestPolicy:
    """Decide whether the robot is awake, drowsy or asleep, and what that looks like."""

    def __init__(
        self,
        now: float,
        *,
        drowsy_after_s: float = DROWSY_AFTER_S,
        asleep_after_s: float = ASLEEP_AFTER_S,
        quiet_hours_active: Callable[[], bool] = lambda: False,
    ) -> None:
        self._drowsy_after_s = drowsy_after_s
        self._asleep_after_s = asleep_after_s
        self._quiet_hours_active = quiet_hours_active
        self._stage: RestStage = "awake"
        self._quiet_since = now

    @property
    def stage(self) -> RestStage:
        return self._stage

    def update(
        self,
        now: float,
        *,
        person_present: bool,
        turn_active: bool,
        sound_level: float = 0.0,
    ) -> RestOutput:
        if person_present or turn_active or sound_level >= WAKE_SOUND_LEVEL:
            self._quiet_since = now
            if self._stage != "awake":
                self._stage = "awake"
                return RestOutput(
                    "awake", PITCH_FRACTION["awake"], FACE_BY_STAGE["awake"], wake_transition=True
                )
            return RestOutput("awake", PITCH_FRACTION["awake"], FACE_BY_STAGE["awake"])
        if self._stage == "asleep":
            return RestOutput("asleep", PITCH_FRACTION["asleep"], FACE_BY_STAGE["asleep"])
        factor = QUIET_HOURS_FACTOR if self._quiet_hours_active() else 1.0
        quiet_for = now - self._quiet_since
        if quiet_for >= self._asleep_after_s * factor:
            self._stage = "asleep"
        elif quiet_for >= self._drowsy_after_s * factor:
            self._stage = "drowsy"
        return RestOutput(self._stage, PITCH_FRACTION[self._stage], FACE_BY_STAGE[self._stage])
