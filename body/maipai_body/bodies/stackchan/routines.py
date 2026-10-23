"""StackChan rest routines: render a RestPolicy output as a face and the resting head pose."""

from __future__ import annotations

import time

from maipai_body.expression.rest import RestOutput
from maipai_body.hal.seam import BodyProfile, HeadActuator, HeadPose

from .avatar.server import control_avatar, sleeping_avatar
from .renderer import pitch_for


class RestRenderer:
    """Send a rest face and head drop, but only when the stage changes."""

    def __init__(
        self,
        *,
        set_brightness=None,
        restore_brightness=None,
        set_ring_sleeping=None,
        sleep_brightness: int = 5,
        blink_delay_s: float = 0.2,
        sleep=None,
    ) -> None:
        self._last_stage: str | None = None
        self._set_brightness = set_brightness
        self._restore_brightness = restore_brightness
        self._set_ring_sleeping = set_ring_sleeping
        self._sleep_brightness = sleep_brightness
        self._blink_delay_s = blink_delay_s
        self._sleep = sleep
        self._sleeping = False

    def render(
        self,
        output: RestOutput,
        client: HeadActuator,
        profile: BodyProfile,
        *,
        pose_held=lambda: False,
    ) -> None:
        if pose_held():
            return
        if output.stage == self._last_stage:
            return
        self._last_stage = output.stage
        sender = getattr(client, "send_avatar_frame", None)
        waking = output.stage == "awake" and output.wake_transition and self._sleeping
        if output.stage == "asleep":
            if callable(sender):
                sender(sleeping_avatar())
            if self._set_brightness is not None:
                self._set_brightness(self._sleep_brightness)
            if self._set_ring_sleeping is not None:
                self._set_ring_sleeping(True)
            self._sleeping = True
        elif waking:
            if callable(sender):
                sender(sleeping_avatar())
                (self._sleep or time.sleep)(self._blink_delay_s)
                sender(control_avatar("neutral"))
            if self._restore_brightness is not None and self._set_brightness is not None:
                self._set_brightness(self._restore_brightness())
            if self._set_ring_sleeping is not None:
                self._set_ring_sleeping(False)
            self._sleeping = False
        elif callable(sender):
            sender(control_avatar("sleepy" if output.stage == "drowsy" else "neutral"))
        # The head only travels up from level, so it cannot "drop" for drowsy or asleep: it rests at
        # level and the sleepy face carries the stage. (The shared rest policy's fraction is a drop
        # for other bodies; used as a pitch here it raised the head to 66 and 85 degrees.)
        pose = HeadPose(yaw=0.0, pitch=pitch_for(profile))
        # Same dispatch as the expression renderer: the robot facade when present,
        # otherwise the lease adapter's set command. Errors raise, nothing is swallowed.
        robot = getattr(client, "robot", None)
        if robot is not None:
            robot.head.set(pose=pose)
        else:
            client.command("set", pose=pose)


_default_renderer = RestRenderer()


def render_rest(
    output: RestOutput,
    client: HeadActuator,
    profile: BodyProfile,
    *,
    renderer: RestRenderer | None = None,
    pose_held=lambda: False,
) -> None:
    """Render a rest output; repeated calls with the same stage are a no-op."""
    (renderer if renderer is not None else _default_renderer).render(
        output, client, profile, pose_held=pose_held
    )


__all__ = ["RestRenderer", "render_rest"]
