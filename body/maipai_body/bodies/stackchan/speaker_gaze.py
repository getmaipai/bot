"""Speaker gaze for StackChan (BOT-SC-GAZE-01): while someone is talking,
gently ease the head toward them. Pure and clock-injected, like
``expression.gaze.GazeController``: ``update`` takes the time, the speaker
evidence and the head's current angles, and returns an absolute target
(``GazeStep``) or ``None`` to do nothing.

The rules are deliberately timid: a dead band, a small clamped step at most
once per second, hard absolute limits, and a single optional bearing turn
per speaking burst. With no face and no bearing the controller never moves:
it must not search or scan.

All numbers below are UNMEASURED design defaults; replace them once the
unit rows in ``docs/dev/measure-runbook.md`` exist. Frame convention:
``face`` is centred in [-1, 1] on each axis, x right positive, y down
positive; yaw and pitch are radians, positive yaw right, positive pitch down.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

FACE_DEADBAND = 0.15  # fraction of frame half-size before a step is taken
STEP_GAIN = 0.35  # rad of head per unit of frame offset
MAX_STEP_RAD = 0.12  # per-axis step clamp
STEP_PERIOD_S = 1.0  # at most one step per this long
MAX_YAW_RAD = 0.6  # absolute yaw limit from center
MAX_PITCH_RAD = 0.3  # absolute pitch limit from center
BEARING_THRESHOLD_RAD = 0.3  # a bearing this far off may turn once
BURST_RESET_S = 2.0  # silence this long starts a new speaking burst


@dataclass(frozen=True)
class GazeStep:
    """An absolute head target: yaw and pitch in radians."""

    yaw: float
    pitch: float


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class SpeakerGaze:
    """Nudge the head toward the speaker, gently, without ever scanning."""

    def __init__(self, *, enabled: Callable[[], bool] = lambda: True) -> None:
        self._enabled = enabled
        self._last_step = -1e9
        self._bearing_used = False
        self._silence_since: float | None = None

    def update(
        self,
        now: float,
        *,
        speaking: bool,
        face: tuple[float, float] | None,
        bearing_rad: float | None,
        yaw: float,
        pitch: float,
    ) -> GazeStep | None:
        """Advance one step. ``None`` means the head is left alone."""
        if not speaking:
            self._track_silence(now)
            return None
        if not self._enabled():
            return None
        self._silence_since = None
        if now - self._last_step < STEP_PERIOD_S:
            return None
        if face is not None:
            return self._face_step(face, yaw, pitch, now)
        return self._bearing_step(bearing_rad, yaw, pitch, now)

    def _track_silence(self, now: float) -> None:
        if self._silence_since is None:
            self._silence_since = now
        elif now - self._silence_since >= BURST_RESET_S:
            self._bearing_used = False
            self._silence_since = None

    def _face_step(
        self, face: tuple[float, float], yaw: float, pitch: float, now: float
    ) -> GazeStep | None:
        fx, fy = face
        if abs(fx) < FACE_DEADBAND and abs(fy) < FACE_DEADBAND:
            return None
        target_yaw = _clamp(
            yaw + _clamp(fx * STEP_GAIN, -MAX_STEP_RAD, MAX_STEP_RAD),
            -MAX_YAW_RAD,
            MAX_YAW_RAD,
        )
        target_pitch = _clamp(
            pitch + _clamp(fy * STEP_GAIN, -MAX_STEP_RAD, MAX_STEP_RAD),
            -MAX_PITCH_RAD,
            MAX_PITCH_RAD,
        )
        if target_yaw == yaw and target_pitch == pitch:
            return None
        self._last_step = now
        return GazeStep(target_yaw, target_pitch)

    def _bearing_step(
        self, bearing_rad: float | None, yaw: float, pitch: float, now: float
    ) -> GazeStep | None:
        if bearing_rad is None or self._bearing_used or abs(bearing_rad) <= BEARING_THRESHOLD_RAD:
            return None
        target_yaw = _clamp(
            yaw + _clamp(bearing_rad * STEP_GAIN, -MAX_STEP_RAD, MAX_STEP_RAD),
            -MAX_YAW_RAD,
            MAX_YAW_RAD,
        )
        if target_yaw == yaw:
            return None
        self._bearing_used = True
        self._last_step = now
        return GazeStep(target_yaw, pitch)
