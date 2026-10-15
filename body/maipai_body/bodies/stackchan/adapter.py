"""Translate the shared robot object to the StackChan xiaozhi tool interface."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from maipai_body.hal.errors import NotSupported
from maipai_body.hal.seam import BodyProfile, HeadPose
from maipai_body.robot import Robot, load_robot_api

from .profile import (
    HEAD_COMMAND_SPEED,
    HEAD_SPEED_MAX,
    HEAD_SPEED_MIN,
    LED_CHANNEL_MAX,
    LED_COUNT,
    STACKCHAN_PROFILE,
)


class StackChanDeviceClient(Protocol):
    """The three supported xiaozhi tool calls plus local queued-target cancellation."""

    def get_head_angles(self) -> Mapping[str, int]: ...

    def set_head_angles(self, yaw: int | None, pitch: int | None, speed: int) -> object: ...

    def set_led_color(self, red: int, green: int, blue: int) -> object: ...

    def set_volume(self, volume: int) -> object: ...

    def cancel_pending(self) -> None: ...


class _HeadAdapter:
    def __init__(self, client: StackChanDeviceClient) -> None:
        self.client = client

    def command(self, verb: str, *args: Any, **kwargs: Any) -> object:
        if verb == "hold":
            self.client.cancel_pending()
            return True
        if verb == "disable":
            raise NotSupported(
                "StackChan has no remote servo torque-disable command",
                part="head",
                capability="head_pan_tilt",
                fix="Use the robot's power switch or unplug it to cut servo power.",
            )
        if verb == "enable":
            raise NotSupported(
                "StackChan has no remote servo torque-enable command",
                part="head",
                capability="head_pan_tilt",
                fix="Use the robot's power switch, then reconnect the StackChan service.",
            )
        if verb not in {"set", "goto"}:
            raise AttributeError(verb)

        pose = kwargs.get("pose", kwargs.get("target"))
        if pose is None and args and isinstance(args[0], (HeadPose, Mapping)):
            pose = args[0]
        if isinstance(pose, HeadPose):
            yaw = pose.yaw
            pitch = pose.pitch
        elif isinstance(pose, Mapping):
            yaw = pose.get("yaw")
            pitch = pose.get("pitch")
        else:
            yaw = kwargs.get("yaw")
            pitch = kwargs.get("pitch")

        applied_yaw = self._degrees(yaw)
        applied_pitch = self._degrees(pitch)
        if applied_yaw is None and applied_pitch is None:
            return {"yaw": None, "pitch": None, "speed": HEAD_COMMAND_SPEED}

        requested_speed = kwargs.get("speed", HEAD_COMMAND_SPEED)
        if not isinstance(requested_speed, (int, float)):
            raise TypeError("head speed must be numeric; use a value from 100 to 1000")
        speed = min(max(round(requested_speed), HEAD_SPEED_MIN), HEAD_COMMAND_SPEED)
        result = self.client.set_head_angles(applied_yaw, applied_pitch, speed)
        if isinstance(result, Mapping):
            return dict(result)
        return {"yaw": applied_yaw, "pitch": applied_pitch, "speed": speed}

    @staticmethod
    def _degrees(value: Any) -> int | None:
        if value is None:
            return None
        if not isinstance(value, (int, float)):
            raise TypeError("head pose angles must be numeric radians")
        return round(math.degrees(value))


class _LedAdapter:
    def __init__(self, client: StackChanDeviceClient) -> None:
        self.client = client

    def command(self, verb: str, *args: Any, **kwargs: Any) -> object:
        if verb == "set":
            raise NotSupported(
                "StackChan's LED tool changes all 12 lights together",
                part="leds",
                capability="light_ring",
                fix="Use leds.many with the same RGB color for all 12 light indexes.",
            )
        if verb != "many":
            raise AttributeError(verb)
        updates = args[0] if args else kwargs.get("updates")
        if not isinstance(updates, Sequence) or isinstance(updates, (str, bytes)):
            raise TypeError("leds.many needs a sequence of index and RGB updates")
        if len(updates) != LED_COUNT:
            raise NotSupported(
                "StackChan can only set the whole LED ring to one color",
                part="leds",
                capability="light_ring",
                fix="Include all 12 light indexes with the same RGB color.",
            )
        colors: list[tuple[int, int, int]] = []
        indexes: set[int] = set()
        for entry in updates:
            if not isinstance(entry, Mapping):
                raise TypeError("each LED update needs an index and an RGB color")
            index = entry.get("index")
            rgb = entry.get("rgb")
            if type(index) is not int or not 0 <= index < LED_COUNT:
                raise ValueError(f"LED index must be from 0 to {LED_COUNT - 1}")
            if index in indexes:
                raise ValueError(f"LED index {index} appears more than once")
            indexes.add(index)
            if not isinstance(rgb, Sequence) or len(rgb) != 3:
                raise ValueError("LED RGB must contain exactly three integer channels")
            if any(
                type(channel) is not int or not 0 <= channel <= LED_CHANNEL_MAX for channel in rgb
            ):
                raise ValueError(f"LED channels must be integers from 0 to {LED_CHANNEL_MAX}")
            colors.append((rgb[0], rgb[1], rgb[2]))
        if indexes != set(range(LED_COUNT)) or len(set(colors)) != 1:
            raise NotSupported(
                "StackChan cannot set separate LED colors",
                part="leds",
                capability="light_ring",
                fix="Use one RGB color for every light index in the ring.",
            )
        return self.client.set_led_color(*colors[0])


class _AudioAdapter:
    def __init__(self, client: StackChanDeviceClient) -> None:
        self.client = client

    def command(self, verb: str, *args: Any, **kwargs: Any) -> object:
        if verb != "speaker.volume":
            raise NotSupported(
                f"StackChan does not expose audio command '{verb}' through xiaozhi",
                part="audio",
                capability="speaker",
                fix="Use the speaker volume control supported by this StackChan service.",
            )
        volume = kwargs.get("volume", args[0] if args else None)
        if type(volume) is not int or not 0 <= volume <= 100:
            raise ValueError("speaker volume must be an integer from 0 to 100")
        return self.client.set_volume(volume)


class _SoftwareEstopAdapter:
    def __init__(self, client: StackChanDeviceClient) -> None:
        self.client = client
        self.engaged = False

    def command(self, verb: str) -> bool:
        if verb == "engage":
            self.engaged = True
            self.client.cancel_pending()
            return True
        if verb == "release":
            self.engaged = False
            return False
        raise AttributeError(verb)


def create_stackchan_robot(
    client: StackChanDeviceClient,
    *,
    profile: BodyProfile = STACKCHAN_PROFILE,
) -> Robot:
    """Build the shared robot object with StackChan's supported tool adapters."""
    return Robot(
        profile,
        {
            "head": _HeadAdapter(client),
            "leds": _LedAdapter(client),
            "audio": _AudioAdapter(client),
            "estop": _SoftwareEstopAdapter(client),
        },
        load_robot_api(),
    )


class StackChanRobotAdapter:
    """The xiaozhi service's small robot interface backed by the shared Robot object."""

    def __init__(self, client: StackChanDeviceClient) -> None:
        self.client = client
        self.robot = create_stackchan_robot(client)

    async def get_head_angles(self) -> Mapping[str, int]:
        return self.client.get_head_angles()

    async def set_head_angles(
        self, yaw: int | None, pitch: int | None, speed: int = HEAD_COMMAND_SPEED
    ) -> object:
        lease = self.robot.lease.acquire("person", "xiaozhi-service")
        try:
            target = {
                "yaw": math.radians(yaw) if yaw is not None else None,
                "pitch": math.radians(pitch) if pitch is not None else None,
                "speed": min(max(speed, HEAD_SPEED_MIN), HEAD_SPEED_MAX),
            }
            return self.robot.head.set(**target)
        finally:
            self.robot.lease.release(lease.holder)

    async def set_led_color(self, red: int, green: int, blue: int) -> object:
        updates = [{"index": index, "rgb": [red, green, blue]} for index in range(LED_COUNT)]
        return self.robot.leds.many(updates)

    async def set_volume(self, volume: int) -> object:
        return self.robot.audio.speaker.volume(volume)


__all__ = ["StackChanRobotAdapter", "StackChanDeviceClient", "create_stackchan_robot"]
