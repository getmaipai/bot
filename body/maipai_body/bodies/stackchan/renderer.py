"""StackChan expression renderer: avatar frames, bounded head poses and ring states."""

from __future__ import annotations

import math

from maipai_body.expression.renderers import register_renderer
from maipai_body.hal.seam import BodyProfile, HeadActuator, HeadPose

from .avatar.server import control_avatar
from .expression_map import (
    CUE_FACE_MAP,
    PRIMITIVE_BODY_MAP,
    REPLY_MOOD_FACE_MAP,
    UNSUPPORTED_PRIMITIVES,
    FaceFrame,
)


def _limit(profile: BodyProfile, axis: str, fraction: float) -> float:
    bound = profile.axis(axis)
    edge = max(abs(bound.min), abs(bound.max)) * fraction
    low, high = bound.min, bound.max
    if bound.unit == "deg":
        edge = math.radians(edge)
        low, high = math.radians(low), math.radians(high)
    if axis == "head_pitch":
        neutral = (low + high) / 2
        edge = neutral + math.copysign(edge, fraction)
    return min(high, max(low, edge))


def render(
    primitive: str,
    client: HeadActuator,
    profile: BodyProfile,
    *,
    doa_angle_rad: float = 0.0,
    real_time: bool = False,
) -> None:
    del real_time
    if primitive in UNSUPPORTED_PRIMITIVES:
        raise NotImplementedError(UNSUPPORTED_PRIMITIVES[primitive])
    try:
        action = PRIMITIVE_BODY_MAP[primitive]
    except KeyError as exc:
        raise ValueError(f"no StackChan rendering declared for primitive {primitive!r}") from exc

    yaw = 0.0
    if action.yaw_fraction:
        direction = doa_angle_rad or 1.0
        sign = 1.0 if direction >= 0 else -1.0
        yaw = sign * _limit(profile, "head_yaw", action.yaw_fraction)
    pitch_axis = profile.axis("head_pitch")
    pitch = (
        _limit(profile, "head_pitch", action.pitch_fraction)
        if action.pitch_fraction
        else math.radians((pitch_axis.min + pitch_axis.max) / 2)
        if pitch_axis.unit == "deg"
        else (pitch_axis.min + pitch_axis.max) / 2
    )
    pose = HeadPose(yaw=yaw, pitch=pitch)
    # Robot's part facade dispatches only methods present on its API; the expression
    # engine ordinarily owns motion through MotionWorker. StackChan's adapter accepts
    # profile-clamped absolute targets via set_target.
    robot = getattr(client, "robot", None)
    if robot is not None:
        robot.head.set(pose=pose)
    else:
        goto = getattr(client, "goto", None)
        if callable(goto):
            goto(pose=pose, duration_s=0.2)
        else:
            client.command("set", pose=pose)
    send = getattr(client, "send_avatar_frame", None)
    if callable(send):
        send(control_avatar(action.face))
    # The ring carries state through the light standard (indicator/looks.py), never expression.


def render_cue(cue: str, client: HeadActuator, *, mood: str | None = None) -> None:
    """Render a turn-state face from the closed cue table."""
    if cue == "reply_mood":
        expression = REPLY_MOOD_FACE_MAP.get(mood or "neutral", "neutral")
        face = FaceFrame(expression)
    else:
        try:
            face = CUE_FACE_MAP[cue]
        except KeyError as exc:
            raise ValueError(f"unknown StackChan turn cue {cue!r}") from exc
    sender = getattr(client, "send_avatar_frame", None)
    if callable(sender):
        sender(control_avatar(face.expression, eyes=face.eyes, mouth=face.mouth))


register_renderer("stackchan", render)

__all__ = ["render", "render_cue"]
