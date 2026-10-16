"""Gaze: the face-following controller (S-EXPR-04, design v2 section 4.1/4.4).

Pure and clock-injected: ``GazeController.update`` takes the time and the
latest face sample and returns the gaze layer's target (or ``None`` to
release the layer). Nothing here touches a motor, so every rule has a
deterministic trajectory test on a manual clock.

Every number is a design default, UNMEASURED until the unit rows in
``docs/dev/measure-runbook.md`` replace them. Frame convention, also
UNVERIFIED on hardware: ``x`` and ``y`` are centred in [-1, 1] (frame
width and height both 2.0), positive x to the right of the image,
positive y down. Yaw is positive to the robot's left, pitch positive down.

Rules implemented: deadband, mapping with send epsilon, dt cap, head
first then body follow with hysteresis, total yaw caps, the 260 ms
body-move ignore window, the 250 ms stale-detection rule, the loss ladder
(coast, drop, ease home, one look-around), and never tilting down past 5
degrees while tracking. Not implemented: multi-face target continuity
(the body's tracker reports one face) and the speaking gaze weight.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_DEG = math.radians(1)

DEADBAND_X = 0.035  # fraction of frame width
DEADBAND_Y = 0.045  # fraction of frame height
YAW_GAIN = 1.1  # rad per unit of frame fraction
PITCH_GAIN = 0.9
SEND_EPSILON_RAD = 0.6 * _DEG
DT_CAP_S = 0.07
HEAD_FIRST_RAD = 0.22  # the head takes this much before the body is asked
BODY_START_DELTA_RAD = 0.35
BODY_STOP_DELTA_RAD = 0.10
BODY_RATE_RAD_S = 0.5
BODY_RATE_PER_DELTA = 2.5
HEAD_DELTA_CAP_RAD = 60.0 * _DEG
BODY_CAP_RAD = 115.0 * _DEG
TOTAL_YAW_CAP_RAD = 175.0 * _DEG
IGNORE_AFTER_BODY_MOVE_S = 0.26
STALE_DETECTION_S = 0.25
MAX_DOWN_PITCH_RAD = 5.0 * _DEG
MAX_UP_PITCH_RAD = 35.0 * _DEG
COAST_S = 0.6
DROP_S = 0.8
EASE_HOME_S = 3.0
LOOK_AROUND_AFTER_S = 6.0
LOOK_AROUND_PERIOD_S = 9.0
LOOK_AROUND_BODY_RAD = 35.0 * _DEG
LOOK_AROUND_HEAD_RAD = 30.0 * _DEG
LOOK_AROUND_HEAD_LEAD_RAD = 0.6


@dataclass(frozen=True)
class FaceSample:
    """One face detection: centred frame coordinates and when it was seen."""

    x: float
    y: float
    seen_at: float


@dataclass(frozen=True)
class GazeOutput:
    """The gaze layer's target. Head yaw is world-frame (body yaw plus the neck's share)."""

    head_yaw: float
    head_pitch: float
    body_yaw: float


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _deadbanded(fraction: float, deadband: float) -> float:
    """Subtract the deadband and keep the sign; inside it the error is zero."""
    magnitude = abs(fraction)
    if magnitude <= deadband:
        return 0.0
    return math.copysign(magnitude - deadband, fraction)


class GazeController:
    """Follow a face with the head, then the body; fall back through the loss ladder."""

    def __init__(self, *, now: float, head_yaw: float = 0.0, body_yaw: float = 0.0) -> None:
        self._head_yaw = head_yaw
        self._head_pitch = 0.0
        self._body_yaw = body_yaw
        self._last_update = now
        self._last_seen: float | None = None
        self._last_body_move = -1e9
        self._following_body = False
        self._sent: GazeOutput | None = None
        self._drop_pose: tuple[float, float, float] | None = None
        self._look_started: float | None = None
        self._released = True

    @property
    def tracking(self) -> bool:
        """True while a face holds the gaze (before the loss ladder runs out)."""
        return self._last_seen is not None

    @property
    def head_yaw(self) -> float:
        return self._head_yaw

    @property
    def body_yaw(self) -> float:
        return self._body_yaw

    def update(self, now: float, face: FaceSample | None) -> GazeOutput | None:
        """Advance one step. ``None`` means the gaze layer is released."""
        dt = _clamp(now - self._last_update, 0.0, DT_CAP_S)
        self._last_update = now

        fresh = face is not None and (now - face.seen_at) <= STALE_DETECTION_S
        if face is not None and fresh:
            self._last_seen = max(self._last_seen or face.seen_at, face.seen_at)
            self._drop_pose = None
            self._look_started = None
            if now - self._last_body_move >= IGNORE_AFTER_BODY_MOVE_S:
                self._steer_head(face)
            self._follow_body(now, dt)
            return self._emit()

        # No usable face: a stale detection never moves a motor.
        if self._last_seen is None:
            return None
        lost_for = now - self._last_seen
        if lost_for < COAST_S:
            return self._emit(force=False)
        if lost_for < DROP_S:
            return self._emit(force=False)
        return self._ladder(now, lost_for)

    def look_at(self, now: float, *, head_yaw: float, body_yaw: float | None = None) -> None:
        """Point the gaze somewhere without a face (a DoA turn); the loss ladder then runs."""
        if body_yaw is not None and abs(body_yaw - self._body_yaw) > 1e-6:
            self._body_yaw = _clamp(body_yaw, -BODY_CAP_RAD, BODY_CAP_RAD)
            self._last_body_move = now
        self._head_yaw = self._clamp_head(head_yaw)
        self._last_seen = now
        self._drop_pose = None
        self._look_started = None
        self._following_body = False
        self._sent = None

    # -- following -------------------------------------------------------

    def _steer_head(self, face: FaceSample) -> None:
        dx = _deadbanded(face.x / 2.0, DEADBAND_X)
        dy = _deadbanded(face.y / 2.0, DEADBAND_Y)
        # A face to the right of the image needs the head turned right (negative yaw).
        yaw = self._head_yaw - dx * YAW_GAIN
        pitch = self._head_pitch + dy * PITCH_GAIN
        self._head_pitch = _clamp(pitch, -MAX_UP_PITCH_RAD, MAX_DOWN_PITCH_RAD)
        self._head_yaw = self._clamp_head(yaw)

    def _clamp_head(self, yaw: float) -> float:
        low = max(self._body_yaw - HEAD_DELTA_CAP_RAD, -TOTAL_YAW_CAP_RAD)
        high = min(self._body_yaw + HEAD_DELTA_CAP_RAD, TOTAL_YAW_CAP_RAD)
        return _clamp(yaw, low, high)

    def _follow_body(self, now: float, dt: float) -> None:
        delta = self._head_yaw - self._body_yaw
        if not self._following_body and abs(delta) > BODY_START_DELTA_RAD:
            self._following_body = True
        if self._following_body and abs(delta) <= BODY_STOP_DELTA_RAD:
            self._following_body = False
        if not self._following_body or dt <= 0.0:
            return
        rate = min(BODY_RATE_RAD_S, abs(delta) * BODY_RATE_PER_DELTA)
        step = min(rate * dt, abs(delta) - BODY_STOP_DELTA_RAD)
        if step <= 0.0:
            return
        moved = self._body_yaw + math.copysign(step, delta)
        self._body_yaw = _clamp(moved, -BODY_CAP_RAD, BODY_CAP_RAD)
        self._last_body_move = now
        self._head_yaw = self._clamp_head(self._head_yaw)

    # -- loss ladder -----------------------------------------------------

    def _ladder(self, now: float, lost_for: float) -> GazeOutput | None:
        if self._drop_pose is None:
            self._drop_pose = (self._head_yaw, self._head_pitch, self._body_yaw)
            self._following_body = False
        head0, pitch0, body0 = self._drop_pose
        if lost_for < DROP_S + EASE_HOME_S:
            progress = (lost_for - DROP_S) / EASE_HOME_S
            eased = progress * progress * (3.0 - 2.0 * progress)
            self._head_yaw = head0 * (1.0 - eased)
            self._head_pitch = pitch0 * (1.0 - eased)
            self._body_yaw = body0 * (1.0 - eased)
            return self._emit()
        self._head_yaw = self._head_pitch = self._body_yaw = 0.0
        if lost_for < LOOK_AROUND_AFTER_S:
            return self._emit()
        if self._look_started is None:
            self._look_started = now
        elapsed = now - self._look_started
        if elapsed >= LOOK_AROUND_PERIOD_S:
            # One look-around, then the layer is released to idle.
            self._last_seen = None
            self._drop_pose = None
            self._look_started = None
            self._sent = None
            return None
        phase = 2.0 * math.pi * elapsed / LOOK_AROUND_PERIOD_S
        body = LOOK_AROUND_BODY_RAD * math.sin(phase)
        head = body + LOOK_AROUND_HEAD_RAD * math.sin(phase + LOOK_AROUND_HEAD_LEAD_RAD)
        self._body_yaw = body
        self._head_yaw = self._clamp_head(head)
        return self._emit()

    # -- output ----------------------------------------------------------

    def _emit(self, *, force: bool = True) -> GazeOutput:
        out = GazeOutput(self._head_yaw, self._head_pitch, self._body_yaw)
        previous = self._sent
        if previous is not None and not force:
            return previous
        if previous is not None and all(
            abs(a - b) < SEND_EPSILON_RAD
            for a, b in (
                (out.head_yaw, previous.head_yaw),
                (out.head_pitch, previous.head_pitch),
                (out.body_yaw, previous.body_yaw),
            )
        ):
            return previous
        self._sent = out
        return out
