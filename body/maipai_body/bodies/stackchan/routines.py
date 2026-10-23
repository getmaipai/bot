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


RETRY_S = 5.0  # a stage whose face could not be sent is tried again this often


def _face_sender(client):
    """The function that sends a face: the client's own, else its expression device's."""
    sender = getattr(client, "send_avatar_frame", None)
    if callable(sender):
        return sender
    device = getattr(client, "expression_device", None)
    sender = getattr(device, "send_avatar_frame", None)
    return sender if callable(sender) else None


class RestRenderer:
    """Show a rest stage once: the face, the screen level, the ring and the resting head pose.

    A stage counts as shown when its face went out. A step that fails is logged and the rest
    still run; a stage whose face failed is tried again every RETRY_S, never on every pass.
    Leaving sleep always restores the screen and the ring, whatever happened to the face."""

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
        clock=time.monotonic,
    ) -> None:
        self._set_brightness = set_brightness
        self._restore_brightness = restore_brightness
        self._set_ring_sleeping = set_ring_sleeping
        self._sleep_brightness = sleep_brightness
        self._blink_delay_s = blink_delay_s
        self._sleep = sleep
        self._firmware_version = firmware_version
        self._quiet_s = quiet_s
        self._thresholds = thresholds
        self._night_active = night_active
        self._clock = clock
        self._sleeping = False  # the screen is dimmed and the ring dark
        self._shown_stage: str | None = None  # the stage whose face went out
        self._announced_stage: str | None = "awake"  # the stage last written to the log
        self._pose_stage: str | None = None  # the stage whose head pose was set
        self._retry_at = float("-inf")
        self._warned_no_sender = False

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
        stage = output.stage
        if stage == self._shown_stage:
            return
        now = self._clock()
        if stage != self._announced_stage:
            drowsy, asleep = self._thresholds()
            LOG.info(
                "StackChan rest: %s -> %s (quiet %d s, thresholds %d/%d, night=%s)",
                self._announced_stage,
                stage,
                int(self._quiet_s()),
                drowsy,
                asleep,
                self._night_active(),
            )
            self._announced_stage = stage
            self._retry_at = float("-inf")
        elif now < self._retry_at:
            return

        def step(name, action):
            try:
                action()
                LOG.info("StackChan rest: %s", name)
                return True
            except Exception:
                LOG.warning("StackChan rest: %s failed", name, exc_info=True)
                return False

        sender = _face_sender(client)
        if sender is None and not self._warned_no_sender:
            self._warned_no_sender = True
            LOG.warning(
                "StackChan rest: this head has no way to send a face; rest faces are skipped"
            )

        face_ok = True  # nothing to send is not a failure
        if stage == "asleep":
            self._sleeping = True  # whatever fails below, waking restores the screen and the ring
            if sender is not None:
                face = (
                    "sleeping"
                    if _version_at_least(self._firmware_version(), SLEEPING_FACE_MIN_FIRMWARE)
                    else "sleepy"
                )
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
        elif stage == "awake" and self._sleeping:
            self._sleeping = False
            if sender is not None:
                step("wake blink on", lambda: sender(sleeping_avatar()))
                step("wake blink delay", lambda: (self._sleep or time.sleep)(self._blink_delay_s))
                face_ok = step("wake blink off", lambda: sender(control_avatar("neutral")))
            if self._restore_brightness is not None and self._set_brightness is not None:
                step(
                    "brightness restored", lambda: self._set_brightness(self._restore_brightness())
                )
            if self._set_ring_sleeping is not None:
                step("ring restored", lambda: self._set_ring_sleeping(False))
        elif sender is not None:
            face_name = "sleepy" if stage == "drowsy" else "neutral"
            face_ok = step(f"face {face_name} sent", lambda: sender(control_avatar(face_name)))

        if self._pose_stage != stage:
            # The head only travels up from level, so it cannot "drop" for drowsy or asleep: it
            # rests at level and the sleepy face carries the stage. (The shared rest policy's
            # fraction is a drop for other bodies; used as a pitch here it raised the head to 66
            # and 85 degrees.)
            pose = HeadPose(yaw=0.0, pitch=pitch_for(profile))
            robot = getattr(client, "robot", None)
            if robot is not None:
                done = step("head pose set", lambda: robot.head.set(pose=pose))
            else:
                done = step("head pose set", lambda: client.command("set", pose=pose))
            if done:
                self._pose_stage = stage
        if face_ok:
            self._shown_stage = stage
        else:
            self._retry_at = now + RETRY_S


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
