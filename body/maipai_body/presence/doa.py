"""Direction-of-arrival front/back disambiguation (S-EXPR-04, design v2 section 4.5).

The microphone array is linear and covers the front 180 degrees only, so a
source behind the robot reads as its mirror in front. ``DoaResolver``
decides, from the reading and one probe turn, where the source really is.

Bearings here are radians relative to the head's forward direction at the
time of the sample, positive to the robot's left. The SDK reports the
angle on its own scale; ``sdk_angle_to_bearing`` is the one place that
converts, and its offset is UNVERIFIED until a unit row measures it
(``docs/dev/measure-runbook.md``).

Rules: a face track within 20 degrees of the bearing confirms it. If not,
and the bearing is within 25 degrees of +-90, the body turns 20 degrees
toward it over 0.6 s and the array is sampled again. A reading that moved
away from zero means the source is behind: the body completes the turn in
two steps (head leading) inside the 160 degree body limit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

_DEG = math.radians(1)

FACE_CONFIRM_RAD = 20.0 * _DEG
SIDE_WINDOW_RAD = 25.0 * _DEG
PROBE_TURN_RAD = 20.0 * _DEG
PROBE_DURATION_S = 0.6
BODY_LIMIT_RAD = 160 * _DEG
HEAD_LEAD_RAD = 65 * _DEG  # the neck's share before the body must follow
# The behind hypothesis must beat the front one by this margin to win.
_PROBE_MIN_CHANGE_RAD = 2.0 * _DEG


def sdk_angle_to_bearing(angle_rad: float) -> float:
    """Convert the SDK's DoA angle to a head-relative bearing, left positive.

    ASSUMPTION, UNVERIFIED on hardware: the SDK reports 0 at the robot's
    left, pi/2 at the front and pi at the right, so bearing = pi/2 - angle.
    """
    return math.pi / 2.0 - angle_rad


def wrap(angle_rad: float) -> float:
    """Wrap to (-pi, pi]."""
    wrapped = math.fmod(angle_rad + math.pi, 2.0 * math.pi)
    if wrapped <= 0.0:
        wrapped += 2.0 * math.pi
    return wrapped - math.pi


class DoaAction(Enum):
    NONE = "none"
    LOOK = "look"  # accept the bearing: turn the head toward it
    PROBE = "probe"  # turn the body a little and sample again
    TURN = "turn"  # source is behind: turn the body to face it


@dataclass(frozen=True)
class DoaDecision:
    """What to do with a bearing. Angles are world-frame (body yaw plus bearing)."""

    action: DoaAction
    head_yaw: float | None = None
    body_yaw: float | None = None
    over_s: float = 0.0


class DoaResolver:
    """Resolve one speech bearing at a time; call ``observe`` per DoA sample."""

    def __init__(self) -> None:
        self._probe_started: float | None = None
        self._probe_bearing = 0.0
        self._probe_sign = 1.0

    @property
    def probing(self) -> bool:
        return self._probe_started is not None

    def observe(
        self,
        now: float,
        *,
        bearing: float,
        body_yaw: float,
        face_bearing: float | None = None,
    ) -> DoaDecision:
        """Feed one speech sample (bearing relative to the head, left positive)."""
        if self._probe_started is not None:
            if now - self._probe_started < PROBE_DURATION_S:
                return DoaDecision(DoaAction.NONE)
            return self._finish_probe(bearing, body_yaw)

        if face_bearing is not None and abs(wrap(face_bearing - bearing)) <= FACE_CONFIRM_RAD:
            return DoaDecision(DoaAction.LOOK, head_yaw=body_yaw + bearing)

        if abs(abs(bearing) - math.pi / 2.0) <= SIDE_WINDOW_RAD:
            self._probe_started = now
            self._probe_bearing = bearing
            self._probe_sign = 1.0 if bearing >= 0.0 else -1.0
            target = _clamp_body(body_yaw + self._probe_sign * PROBE_TURN_RAD)
            return DoaDecision(
                DoaAction.PROBE,
                head_yaw=target,
                body_yaw=target,
                over_s=PROBE_DURATION_S,
            )

        return DoaDecision(DoaAction.LOOK, head_yaw=body_yaw + bearing)

    def _finish_probe(self, bearing: float, body_yaw: float) -> DoaDecision:
        """Compare the re-sampled bearing with what each hypothesis predicted.

        With ``b`` the magnitude read before the probe turn: a source truly in
        front reads ``b - 20`` degrees afterwards. A source behind reads
        ``180 - b - 20`` once the turn has carried it across the side line
        (``b >= 70``), otherwise ``b + 20``. The nearer prediction wins; a tie
        goes to front.
        """
        before = abs(self._probe_bearing)
        after = abs(bearing)
        sign = self._probe_sign
        self._probe_started = None
        expected_front = before - PROBE_TURN_RAD
        crossed = before >= math.pi / 2.0 - PROBE_TURN_RAD
        expected_behind = (
            (math.pi - before - PROBE_TURN_RAD) if crossed else before + PROBE_TURN_RAD
        )
        if abs(after - expected_behind) + _PROBE_MIN_CHANGE_RAD >= abs(after - expected_front):
            return DoaDecision(DoaAction.LOOK, head_yaw=body_yaw + bearing)
        # The source is behind. After a crossing it now reads as itself, in front.
        true_bearing = sign * (after if crossed else math.pi - after)
        goal = _clamp_body(body_yaw + true_bearing)
        return DoaDecision(
            DoaAction.TURN,
            head_yaw=body_yaw + true_bearing,
            body_yaw=goal,
            over_s=2.0 * PROBE_DURATION_S,
        )


def _clamp_body(yaw: float) -> float:
    return max(-BODY_LIMIT_RAD, min(BODY_LIMIT_RAD, yaw))
