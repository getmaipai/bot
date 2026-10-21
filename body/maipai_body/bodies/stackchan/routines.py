"""StackChan rest routines: render a RestPolicy output as a face and the resting head pose."""

from __future__ import annotations

from maipai_body.expression.rest import RestOutput
from maipai_body.hal.seam import BodyProfile, HeadActuator, HeadPose

from .avatar.server import control_avatar
from .renderer import pitch_for


class RestRenderer:
    """Send a rest face and head drop, but only when the stage changes."""

    def __init__(self) -> None:
        self._last_stage: str | None = None

    def render(self, output: RestOutput, client: HeadActuator, profile: BodyProfile) -> None:
        if output.stage == self._last_stage:
            return
        self._last_stage = output.stage
        sender = getattr(client, "send_avatar_frame", None)
        if callable(sender):
            # Always the calm neutral face. The firmware's sleepy face (u-shaped eyes and a small
            # open mouth, with a "Zzz" bubble) looked creepy after ten idle minutes (2026-10-21);
            # the stage still shows in the level head and, at night, the dark face.
            sender(control_avatar("neutral"))
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
) -> None:
    """Render a rest output; repeated calls with the same stage are a no-op."""
    (renderer if renderer is not None else _default_renderer).render(output, client, profile)


__all__ = ["RestRenderer", "render_rest"]
