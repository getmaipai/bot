"""StackChan rest routines: render a RestPolicy output as a face and the resting head pose."""

from __future__ import annotations

import logging
import time

from maipai_body.expression.rest import RestOutput
from maipai_body.hal.seam import BodyProfile, HeadActuator, HeadPose

from .avatar.server import control_avatar, sleeping_avatar
from .renderer import pitch_for

LOG = logging.getLogger(__name__)
SLEEPING_FACE_MIN_FIRMWARE = (0, 2, 54)


def _version_at_least(value, minimum):
    try:
        parts = tuple(int(part) for part in str(value).split(".")[:3])
        return len(parts) == 3 and parts >= minimum
    except (TypeError, ValueError):
        return False


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
        firmware_version=lambda: None,
        quiet_s=lambda: 0,
        thresholds=lambda: (120, 300),
        night_active=lambda: False,
    ) -> None:
        self._last_stage: str | None = "awake"
        self._set_brightness = set_brightness
        self._restore_brightness = restore_brightness
        self._set_ring_sleeping = set_ring_sleeping
        self._sleep_brightness = sleep_brightness
        self._blink_delay_s = blink_delay_s
        self._sleep = sleep
        self._sleeping = False
        self._face_stage_ok = False
        self._firmware_version = firmware_version
        self._quiet_s = quiet_s
        self._thresholds = thresholds
        self._night_active = night_active

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
        stage_changed = output.stage != self._last_stage
        if not stage_changed and self._last_stage == output.stage and self._face_stage_ok:
            return
        sender = getattr(client, "send_avatar_frame", None)
        waking = output.stage == "awake" and self._sleeping
        if stage_changed:
            old = self._last_stage or "awake"
            drowsy, asleep = self._thresholds()
            quiet_s = self._quiet_s()
            LOG.info(
                "StackChan rest: %s -> %s (quiet %d s, thresholds %d/%d, night=%s)",
                old,
                output.stage,
                int(quiet_s),
                drowsy,
                asleep,
                self._night_active(),
            )
        face_ok = False

        def step(name, action):
            try:
                action()
                LOG.info("StackChan rest: %s", name)
                return True
            except Exception:
                LOG.warning("StackChan rest: %s failed", name, exc_info=True)
                return False

        if output.stage == "asleep":
            version = self._firmware_version()
            face = (
                "sleeping" if _version_at_least(version, SLEEPING_FACE_MIN_FIRMWARE) else "sleepy"
            )
            face_ok = False
            if callable(sender):
                frame = sleeping_avatar()
                if face == "sleepy":
                    frame.expression = "sleepy"
                face_ok = step(f"face {face} sent", lambda: sender(frame))
            if self._set_brightness is not None:
                step(
                    f"brightness set to {self._sleep_brightness}",
                    lambda: self._set_brightness(self._sleep_brightness),
                )
            if self._set_ring_sleeping is not None:
                step("ring dark", lambda: self._set_ring_sleeping(True))
            if face_ok:
                self._sleeping = True
        elif waking:
            face_ok = False
            if callable(sender):
                step("wake blink on", lambda: sender(sleeping_avatar()))
                step("wake blink delay", lambda: (self._sleep or time.sleep)(self._blink_delay_s))
                face_ok = step("wake blink off", lambda: sender(control_avatar("neutral")))
            if self._restore_brightness is not None and self._set_brightness is not None:
                step(
                    "brightness restored", lambda: self._set_brightness(self._restore_brightness())
                )
            if self._set_ring_sleeping is not None:
                step("ring restored", lambda: self._set_ring_sleeping(False))
            if face_ok:
                self._sleeping = False
        elif callable(sender):
            face_name = "sleepy" if output.stage == "drowsy" else "neutral"
            face_ok = step(f"face {face_name} sent", lambda: sender(control_avatar(face_name)))
        # The head only travels up from level, so it cannot "drop" for drowsy or asleep: it rests at
        # level and the sleepy face carries the stage. (The shared rest policy's fraction is a drop
        # for other bodies; used as a pitch here it raised the head to 66 and 85 degrees.)
        pose = HeadPose(yaw=0.0, pitch=pitch_for(profile))
        # Same dispatch as the expression renderer: the robot facade when present,
        # otherwise the lease adapter's set command. Errors raise, nothing is swallowed.
        robot = getattr(client, "robot", None)
        if robot is not None:
            step("head pose set", lambda: robot.head.set(pose=pose))
        else:
            step("head pose set", lambda: client.command("set", pose=pose))
        if face_ok:
            self._last_stage = output.stage
        self._face_stage_ok = face_ok


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
