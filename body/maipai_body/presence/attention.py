"""Attention: glue from presence observations to the gaze and idle layers (S-EXPR-04).

``Attention.step`` is called once per presence tick. It feeds the pure
``GazeController``, ``IdlePolicy`` and ``DoaResolver`` and writes their
output to the expression engine's gaze and idle layers. When a run loop
is given an ``Attention`` it replaces the daemon's own tracker; without
one, ``run_loop`` keeps the daemon path unchanged.

The presence tick runs at ``presence_interval_s`` (0.5 s by default, a
UNMEASURED default); gaze wants about 0.1 s. The controller caps ``dt``
at 70 ms, so a slower tick moves smoothly but late.
"""

from __future__ import annotations

import random
from collections.abc import Callable

from maipai_body.expression.gaze import FaceSample, GazeController, GazeOutput
from maipai_body.expression.idle import IdleLevel, IdlePolicy
from maipai_body.hal.seam import AntennaPositions, HeadPose
from maipai_body.presence.doa import DoaAction, DoaResolver, sdk_angle_to_bearing
from maipai_body.presence.observations import PresenceObservation

# A face counts as "present" for idle micro-poses this long after it was last seen.
_PRESENT_GRACE_S = 5.0
# Several faces: keep following the one nearest the last target while it stays within
# this distance (frame units, UNMEASURED); past it the primary face takes over.
CONTINUITY_RADIUS = 0.35


def pick_face(
    faces: tuple[tuple[float, float], ...],
    primary: tuple[float, float],
    previous: tuple[float, float] | None,
) -> tuple[float, float]:
    """Target continuity across several faces: stay on the face we were following."""
    candidates = faces or (primary,)
    if previous is None:
        return primary
    nearest = min(candidates, key=lambda f: (f[0] - previous[0]) ** 2 + (f[1] - previous[1]) ** 2)
    distance = ((nearest[0] - previous[0]) ** 2 + (nearest[1] - previous[1]) ** 2) ** 0.5
    return nearest if distance <= CONTINUITY_RADIUS else primary


class _Layers:
    """The slice of ExpressionEngine this module drives."""

    def set_gaze(self, pose: HeadPose, body_yaw: float) -> None: ...
    def clear_gaze(self) -> None: ...
    def set_idle(self, pose: HeadPose, antennas: AntennaPositions | None) -> None: ...
    def clear_idle(self) -> None: ...


class Attention:
    def __init__(
        self,
        engine: _Layers,
        *,
        clock: Callable[[], float],
        level_provider: Callable[[], IdleLevel] = lambda: "calm",
        rng: random.Random | None = None,
    ) -> None:
        now = clock()
        self._engine = engine
        self._clock = clock
        self._gaze = GazeController(now=now)
        self._idle = IdlePolicy(now=now, level_provider=level_provider, rng=rng)
        self._doa = DoaResolver()
        self._last_gaze: GazeOutput | None = None
        self._last_face_seen: float | None = None
        self._followed: tuple[float, float] | None = None
        self._gaze_active = False
        self._idle_active = False

    @property
    def gaze(self) -> GazeController:
        return self._gaze

    def release(self) -> None:
        """Drop both layers (stop, service, held, sleep, speaking)."""
        if self._gaze_active:
            self._engine.clear_gaze()
            self._gaze_active = False
        if self._idle_active:
            self._engine.clear_idle()
            self._idle_active = False
        self._last_gaze = None

    def step(self, observation: PresenceObservation, *, seen_at: float | None = None) -> None:
        now = self._clock()
        stamp = seen_at if seen_at is not None else observation.t_received_ns / 1e9
        face: FaceSample | None = None
        if observation.face_detected and observation.face_x is not None:
            x, y = pick_face(
                observation.faces,
                (observation.face_x, observation.face_y or 0.0),
                self._followed if now - (self._last_face_seen or -1e9) < 1.0 else None,
            )
            face = FaceSample(x, y, stamp)
            self._followed = (x, y)
            self._last_face_seen = stamp
        if face is None:
            self._point_at_sound(now, observation)

        out = self._gaze.update(now, face)
        if out is None:
            if self._gaze_active:
                self._engine.clear_gaze()
                self._gaze_active = False
            self._last_gaze = None
        else:
            if out is not self._last_gaze:
                self._engine.set_gaze(
                    HeadPose(yaw=out.head_yaw, pitch=out.head_pitch), out.body_yaw
                )
                self._idle.notify_move(now)
            self._gaze_active = True
            self._last_gaze = out

        present = (
            self._last_face_seen is not None and now - self._last_face_seen <= _PRESENT_GRACE_S
        )
        idle = self._idle.update(
            now, person_present=present, user_speaking=observation.speech_detected
        )
        if idle is None:
            return
        self._engine.set_idle(
            HeadPose(pitch=idle.pitch, roll=idle.roll, yaw=idle.yaw),
            AntennaPositions(left=idle.antenna_left, right=idle.antenna_right),
        )
        self._idle_active = True

    def _point_at_sound(self, now: float, observation: PresenceObservation) -> None:
        if observation.doa_angle_rad is None:
            return
        body = self._gaze.body_yaw
        # The array reads relative to the head; the resolver works relative to the body.
        bearing = sdk_angle_to_bearing(observation.doa_angle_rad) + (self._gaze.head_yaw - body)
        if observation.speech_detected:
            decision = self._doa.observe(now, bearing=bearing, body_yaw=body)
            if decision.action in (DoaAction.LOOK, DoaAction.PROBE, DoaAction.TURN):
                assert decision.head_yaw is not None
                self._gaze.look_at(now, head_yaw=decision.head_yaw, body_yaw=decision.body_yaw)
            return
        look = self._idle.sound_look(now, bearing=bearing)
        if look is not None:
            self._gaze.look_at(now, head_yaw=body + look)
