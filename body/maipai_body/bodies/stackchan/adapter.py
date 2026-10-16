"""Translate the shared robot object to the StackChan xiaozhi tool interface."""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from maipai_body.hal.errors import BodyLost, NotSupported
from maipai_body.hal.seam import BodyProfile, HeadPose
from maipai_body.robot import Robot, load_robot_api

from .avatar_frames import start_camera_stream, stop_camera_stream
from .profile import (
    HEAD_COMMAND_SPEED,
    LED_CHANNEL_MAX,
    LED_COUNT,
    STACKCHAN_NOTIFY_ENABLED,
    STACKCHAN_PROFILE,
)


class StackChanDeviceClient(Protocol):
    """The three supported xiaozhi tool calls plus local queued-target cancellation."""

    def get_head_angles(self) -> Mapping[str, int]: ...

    def set_head_angles(self, yaw: int | None, pitch: int | None, speed: int) -> object: ...

    def set_led_color(self, red: int, green: int, blue: int) -> object: ...

    def set_led_colors(self, colors: list[tuple[int, int, int]]) -> object: ...

    def set_volume(self, volume: int) -> object: ...

    def cancel_pending(self) -> None: ...

    def take_photo(self) -> bytes | None: ...

    def send_avatar_frame(self, frame: bytes) -> object: ...

    def measure_unit(self) -> Mapping[str, Any]: ...

    def get_battery_status(self) -> Mapping[str, Any]: ...

    def push_action(self, action: str, arguments: Mapping[str, Any]) -> object: ...

    def notify(self, audio_url: str) -> object: ...

    def device_supports(self, feature: str) -> bool: ...


class _HeadAdapter:
    def __init__(self, client: StackChanDeviceClient, profile: BodyProfile) -> None:
        self.client = client
        self.profile = profile
        self.expression_device: _ExpressionDevice | None = None

    def command(self, verb: str, *args: Any, **kwargs: Any) -> object:
        if verb == "hold":
            self.client.cancel_pending()
            angles = self.client.get_head_angles()
            self.client.set_head_angles(angles["yaw"], angles["pitch"], HEAD_COMMAND_SPEED)
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
            raise TypeError("head speed must be numeric; use a value from 100 to 150")
        speed = round(requested_speed)
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
        self.camera_indicator_active = False

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
        if indexes != set(range(LED_COUNT)):
            raise NotSupported(
                "StackChan requires an update for each LED index",
                part="leds",
                capability="light_ring",
                fix="Include all 12 light indexes.",
            )
        if self.camera_indicator_active:
            return self.client.set_led_color(LED_CHANNEL_MAX, 0, 0)
        return self.client.set_led_colors(colors)


class _AudioAdapter:
    def __init__(self, client: StackChanDeviceClient, proactive_policy) -> None:
        self.client = client
        self.policy = proactive_policy

    def command(self, verb: str, *args: Any, **kwargs: Any) -> object:
        if verb == "speaker.speak":
            text = kwargs.get("text", args[0] if args else None)
            if not isinstance(text, str) or not text.strip():
                raise ValueError("speaker.speak needs non-empty text")
            if not self.policy("speak"):
                raise NotSupported(
                    "Proactive speech is denied by the active household policy",
                    part="audio",
                    capability="speaker",
                    fix="Change the household quiet-hours or surface policy, then retry.",
                )
            return self.client.push_action("speak", {"text": text})
        if verb == "listen_window":
            duration = kwargs.get("duration_seconds", args[0] if args else None)
            if not self.policy("listen_window"):
                raise NotSupported(
                    "Listen window is denied by the active household policy",
                    part="audio",
                    capability="speaker",
                    fix="Change the household surface policy, then retry.",
                )
            return self.client.push_action("listen_window", {"duration_seconds": duration})
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


class _PushAdapter:
    def __init__(
        self, client: StackChanDeviceClient, proactive_policy, queue, notify_enabled
    ) -> None:
        self.client, self.policy, self.queue = client, proactive_policy, queue
        self.notify_enabled = notify_enabled

    def command(self, verb: str, *args: Any, **kwargs: Any) -> object:
        action = verb
        arguments = dict(kwargs)
        if args and verb == "create_reminder":
            arguments.setdefault("message", args[0])
        if not self.policy(action):
            raise NotSupported(
                f"StackChan {action} is denied by the active quiet-hours or surface policy",
                part="audio" if action in {"speaker.speak", "listen_window"} else "alerts",
                capability="speaker",
                fix="Change the household quiet-hours or surface policy, then retry.",
            )
        try:
            if action == "show" and self.notify_enabled and self.client.device_supports("notify"):
                audio_url = self.client.create_notification_audio(arguments.get("message", "Alert"))
                return self.client.notify(audio_url)
            return self.client.push_action(action, arguments)
        except BodyLost:
            if action == "show":
                self.client.set_led_color(168, 36, 0)
                return self.client.push_action("speak", {"text": arguments.get("message", "Alert")})
            if action in {"create_reminder", "stop_reminder"}:
                self.queue.append((action, arguments))
            raise


class _SoftwareEstopAdapter:
    def __init__(self, client: StackChanDeviceClient) -> None:
        self.client = client
        self.engaged = False

    def command(self, verb: str) -> bool:
        if verb == "engage":
            self.engaged = True
            return True
        if verb == "release":
            self.engaged = False
            return False
        raise AttributeError(verb)


class _CameraAdapter:
    """Camera commands through Robot; the translator owns stream starts."""

    def __init__(self, client: StackChanDeviceClient, robot: Robot) -> None:
        self.client = client
        self.robot = robot
        self.avatar_server: Any = None
        self.device_id: str | None = None
        self._stream_indicator_active = False

    def command(self, verb: str, *args: Any, **kwargs: Any) -> object:
        if verb == "frame":
            if args or kwargs:
                raise TypeError("camera.frame takes no arguments")
            self._light_on()
            try:
                return self.client.take_photo()
            finally:
                self._light_off()
        if verb == "stream_frame":
            deadline = args[0] if args else kwargs.get("deadline_s", 0.4)
            if kwargs.keys() - {"deadline_s"} or args and kwargs:
                raise TypeError("camera.stream_frame accepts one deadline in seconds")
            if not isinstance(deadline, (int, float)) or not 0 < deadline <= 1.0:
                raise ValueError("camera stream frame deadline must be over 0 and at most 1 second")
            if self.avatar_server is None:
                return None
            if self.device_id is None:
                return None
            started = time.monotonic()
            self._light_on()
            self._stream_indicator_active = True
            try:
                device_id = self.device_id
                if device_id not in self.avatar_server._camera_frames:
                    self.avatar_server.wait_camera_device_frame(device_id, timeout=float(deadline))
                frame = self.avatar_server.pop_camera_frame(
                    device_id, max_age_s=min(float(deadline), 0.5)
                )
                if frame is None or time.monotonic() - started > deadline:
                    return None
                return frame
            except BaseException:
                self._light_off()
                self._stream_indicator_active = False
                raise
        if verb != "stream":
            raise AttributeError(verb)
        enabled = kwargs.get("enabled", args[0] if args else True)
        if type(enabled) is not bool:
            raise TypeError("camera.stream enabled must be a boolean")
        from maipai_body.hal.errors import EstopEngaged

        if enabled and self.robot.estop.engaged:
            raise EstopEngaged("camera stream refused while the emergency stop is engaged")
        if enabled:
            self._light_on()
            try:
                self.client.send_avatar_frame(start_camera_stream())
                return True
            except Exception:
                self._light_off()
                raise
        try:
            return self.client.send_avatar_frame(stop_camera_stream())
        finally:
            self._light_off()

    def stream_frame(self, deadline_s: float) -> bytes | None:
        return self.command("stream_frame", deadline_s)

    def stream_frame_done(self) -> None:
        if self._stream_indicator_active:
            self._light_off()
            self._stream_indicator_active = False

    def disconnected(self) -> None:
        if self.avatar_server is not None and self.device_id is not None:
            self.avatar_server.clear_camera_frame(self.device_id)
        if self._stream_indicator_active:
            self._stream_indicator_active = False
        self._light_off()

    def _light_on(self) -> None:
        self.robot._driver("leds").camera_indicator_active = True
        self.robot.leds.many(
            [{"index": index, "rgb": [LED_CHANNEL_MAX, 0, 0]} for index in range(LED_COUNT)]
        )

    def _light_off(self) -> None:
        try:
            self.robot.leds.many([{"index": index, "rgb": [0, 0, 0]} for index in range(LED_COUNT)])
        finally:
            self.robot._driver("leds").camera_indicator_active = False


class _ExpressionDevice:
    """Renderer side-channel bound to the same profile-checked Robot parts."""

    def __init__(self, robot: Robot, client: StackChanDeviceClient) -> None:
        self.robot = robot
        self.client = client

    def goto(self, *, pose: HeadPose, duration_s: float = 0.2) -> object:
        return self.robot.head.set(pose=pose, duration_s=duration_s)

    def hold(self) -> object:
        return self.robot.head.hold()

    def send_avatar_frame(self, frame: bytes) -> None:
        self.client.send_avatar_frame(frame)

    def set_expression_led(self, color: tuple[int, int, int], *, count: int) -> object:
        if count != LED_COUNT:
            raise ValueError("StackChan expression LED update must include the full ring")
        return self.robot.leds.many(
            [{"index": index, "rgb": list(color)} for index in range(count)]
        )


class _UnsupportedSensorAdapter:
    """Expose a sensor part while directing callers to the unit-arrival kit."""

    def __init__(self, part: str, capability: str) -> None:
        self.part = part
        self.capability = capability

    def command(self, verb: str, *args: Any, **kwargs: Any) -> object:
        del verb, args, kwargs
        raise NotSupported(
            f"StackChan {self.part} readings are not verified on a real unit",
            part=self.part,
            capability=self.capability,
            fix=(
                "Run the StackChan unit measurement kit on a paired unit, "
                "then add a verified adapter."
            ),
        )

    def read(self, field: str) -> object:
        del field
        return self.command("read")


class _BatteryAdapter:
    """Read the firmware's read-only AXP2101 status tool on demand."""

    def __init__(self, client: StackChanDeviceClient) -> None:
        self.client = client

    def read(self, field: str) -> object:
        try:
            status = self.client.get_battery_status()
        except NotSupported:
            raise
        except Exception as exc:
            raise BodyLost("StackChan battery status read failed or timed out.") from exc
        if (
            not isinstance(status, Mapping)
            or type(status.get("percent")) is not int
            or not 0 <= status["percent"] <= 100
            or type(status.get("charging")) is not bool
        ):
            raise BodyLost("StackChan returned invalid battery status.")
        if field == "level":
            return status["percent"]
        if field == "charging":
            return status["charging"]
        if field == "state":
            return {"percent": status["percent"], "charging": status["charging"]}
        if field in {"low", "critical"}:
            return None
        raise AttributeError(field)


def create_stackchan_robot(
    client: StackChanDeviceClient,
    *,
    profile: BodyProfile = STACKCHAN_PROFILE,
    proactive_policy=lambda _action: False,
    reminder_queue=None,
    notify_enabled: bool = STACKCHAN_NOTIFY_ENABLED,
) -> Robot:
    """Build the shared robot object with StackChan's supported tool adapters."""
    queue = reminder_queue if reminder_queue is not None else deque()
    push = _PushAdapter(client, proactive_policy, queue, notify_enabled)
    robot = Robot(
        profile,
        {
            "head": _HeadAdapter(client, profile),
            "leds": _LedAdapter(client),
            "audio": _AudioAdapter(client, proactive_policy),
            "estop": _SoftwareEstopAdapter(client),
            "battery": _BatteryAdapter(client),
            "touch": _UnsupportedSensorAdapter("touch", "touch"),
            "imu": _UnsupportedSensorAdapter("imu", "imu"),
            "alerts": push,
            "reminders": push,
        },
        load_robot_api(),
    )
    robot._drivers["camera"] = _CameraAdapter(client, robot)
    expression_device = _ExpressionDevice(robot, client)
    robot._drivers["head"].expression_device = expression_device
    robot._drivers["expression"] = expression_device

    robot._unsupported_fixes = {
        "touch": (
            "Pinned xiaozhi MCP tools include no touch read tool. Run the StackChan unit "
            "measurement kit on a paired unit before adding a verified adapter."
        ),
        "imu": (
            "Pinned xiaozhi MCP tools include no IMU read tool. Run the StackChan unit "
            "measurement kit on a paired unit before adding a verified adapter."
        ),
    }
    return robot


class StackChanRobotAdapter:
    """The xiaozhi service's small robot interface backed by the shared Robot object."""

    def __init__(
        self,
        client: StackChanDeviceClient,
        *,
        proactive_policy=lambda _action: False,
        notify_enabled: bool = STACKCHAN_NOTIFY_ENABLED,
    ) -> None:
        self.client = client
        self.queued_reminders = deque()
        self.proactive_policy = proactive_policy
        self.robot = create_stackchan_robot(
            client,
            proactive_policy=proactive_policy,
            reminder_queue=self.queued_reminders,
            notify_enabled=notify_enabled,
        )
        self.expression = self.robot._driver("expression")

    def flush_reminders(self) -> None:
        while self.queued_reminders:
            action, arguments = self.queued_reminders[0]
            self.client.push_action(action, arguments)
            self.queued_reminders.popleft()

    async def get_head_angles(self) -> Mapping[str, int]:
        return await asyncio.to_thread(self.client.get_head_angles)

    async def set_head_angles(
        self, yaw: int | None, pitch: int | None, speed: int = HEAD_COMMAND_SPEED
    ) -> object:
        return await asyncio.to_thread(self._set_head_angles, yaw, pitch, speed)

    def _set_head_angles(self, yaw: int | None, pitch: int | None, speed: int) -> object:
        target = {
            "yaw": math.radians(yaw) if yaw is not None else None,
            "pitch": math.radians(pitch) if pitch is not None else None,
            "speed": speed,
        }
        return self.robot.head.set(**target)

    async def set_led_color(self, red: int, green: int, blue: int) -> object:
        return await asyncio.to_thread(self._set_led_color, red, green, blue)

    def _set_led_color(self, red: int, green: int, blue: int) -> object:
        return self.client.set_led_color(red, green, blue)

    async def set_volume(self, volume: int) -> object:
        return await asyncio.to_thread(self.robot.audio.speaker.volume, volume)

    async def take_photo(self) -> bytes | None:
        return await asyncio.to_thread(self.robot.camera.frame)

    def send_avatar_frame(self, frame: bytes) -> object:
        return self.client.send_avatar_frame(frame)

    async def stream_camera(self, enabled: bool = True) -> object:
        return await asyncio.to_thread(self.robot.camera.stream, enabled=enabled)

    def camera_disconnected(self) -> None:
        self.robot._driver("camera").disconnected()

    def bind_avatar_camera(self, avatar_server: Any, device_id: str | None) -> None:
        """Connect the authenticated avatar buffer to the Robot camera part."""
        camera = self.robot._driver("camera")
        camera.avatar_server = avatar_server
        camera.device_id = device_id

    def camera_stream_frame(self, deadline_s: float) -> bytes | None:
        return self.robot._driver("camera").stream_frame(deadline_s)


__all__ = ["StackChanRobotAdapter", "StackChanDeviceClient", "create_stackchan_robot"]
