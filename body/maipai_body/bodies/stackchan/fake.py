"""Offline fake xiaozhi device client for StackChan adapter tests."""

from __future__ import annotations

from dataclasses import dataclass

from maipai_body.hal.errors import BodyLost


@dataclass(frozen=True)
class FakeToolCall:
    name: str
    arguments: dict[str, int | None]


class FakeStackChanDeviceClient:
    """Record device tool calls and expose a switchable lost-link failure."""

    def __init__(self) -> None:
        self.connected = True
        self.head_angles = {"yaw": 0, "pitch": 45}
        self.volume = 50
        self.led_color = (0, 0, 0)
        self.led_colors = ((0, 0, 0),) * 12
        self._camera_indicator_active = False
        self._camera_indicator_depth = 0
        self._camera_indicator_saved: list[tuple[int, int, int]] | None = None
        self.calls: list[FakeToolCall] = []
        self.pending_motion: list[object] = []
        self.cancelled_motion_batches = 0
        self.photo: bytes | None = None
        self.avatar_frames: list[bytes] = []
        self.battery_status: dict[str, object] = {"percent": 75, "charging": False}
        self.battery_error: Exception | None = None
        self.push_actions: list[tuple[str, dict[str, object]]] = []
        self.supported_push_actions = {
            "speak",
            "alert",
            "create_reminder",
            "get_reminders",
            "stop_reminder",
            "listen_window",
        }
        self.notify_feature = False
        self.notification_audio_url = "http://192.0.2.10:8766/notify/fake/audio.ogg"
        self.reminders: list[dict[str, object]] = []

        self.measurement_data = {
            "servo_limits_deg": {"yaw": [-128, 128], "pitch": [5, 85]},
            "camera": {"fps": 5.0, "latency_ms": 120.0},
            "aec": {"enabled": True, "quality": "simulated"},
            "battery": {"level_percent": 75, "charging": False},
            "base_mcp_tools": [
                "self.robot.get_head_angles",
                "self.robot.set_head_angles",
                "self.robot.set_led_color",
                "self.audio_speaker.set_volume",
                "self.battery.get_status",
            ],
            "mcp_results": {
                "self.battery.get_status": {"percent": 75, "charging": False},
            },
        }

    def measure_unit(self):
        """Return labeled fixture data for the offline unit-arrival kit."""
        return dict(self.measurement_data)

    def get_head_angles(self) -> dict[str, int]:
        self._require_link()
        self.calls.append(FakeToolCall("self.robot.get_head_angles", {}))
        return dict(self.head_angles)

    def set_head_angles(
        self, yaw: int | None, pitch: int | None, speed: int
    ) -> dict[str, int | None]:
        self._require_link()
        arguments = {"yaw": yaw, "pitch": pitch, "speed": speed}
        self.calls.append(FakeToolCall("self.robot.set_head_angles", arguments))
        if yaw is not None:
            self.head_angles["yaw"] = yaw
        if pitch is not None:
            self.head_angles["pitch"] = pitch
        return arguments

    def set_led_color(self, red: int, green: int, blue: int) -> dict[str, int]:
        self._require_link()
        self.led_color = (red, green, blue)
        self.led_colors = ((red, green, blue),) * 12
        arguments = {"red": red, "green": green, "blue": blue}
        self.calls.append(FakeToolCall("self.robot.set_led_color", arguments))
        return arguments

    def set_led_colors(self, colors: list[tuple[int, int, int]]) -> dict[str, bool]:
        self._require_link()
        if len(colors) != 12:
            raise ValueError("StackChan LED tool needs exactly 12 colors")
        colors = list(colors)
        if self._camera_indicator_active or self._camera_indicator_depth:
            self.led_color = (168, 0, 0)
            self.led_colors = ((168, 0, 0),) * 12
        else:
            self.led_colors = tuple(colors)
            self.led_color = colors[0] if len(set(colors)) == 1 else (-1, -1, -1)
        arguments = {f"led_{index}": color for index, color in enumerate(colors)}
        self.calls.append(FakeToolCall("self.robot.set_led_colors", arguments))
        return {"accepted": True}

    def set_volume(self, volume: int) -> dict[str, int]:
        self._require_link()
        self.volume = volume
        arguments = {"volume": volume}
        self.calls.append(FakeToolCall("self.audio_speaker.set_volume", arguments))
        return arguments

    def get_battery_status(self) -> dict[str, object]:
        self._require_link()
        self.calls.append(FakeToolCall("self.battery.get_status", {}))
        if self.battery_error is not None:
            raise self.battery_error
        return dict(self.battery_status)

    def push_action(self, action: str, arguments) -> object:
        self._require_link()
        if action not in self.supported_push_actions:
            if action == "alert":
                self.calls.append(
                    FakeToolCall(
                        "self.robot.set_led_color",
                        {"red": 168, "green": 36, "blue": 0},
                    )
                )
                self.led_color = (168, 36, 0)
                self.push_actions.append(("speak", {"text": arguments.get("message", "Alert")}))
                return True
            raise BodyLost(f"StackChan does not support {action}")
        payload = dict(arguments)
        self.push_actions.append((action, payload))
        if action == "create_reminder":
            self.reminders.append(payload)
        elif action == "get_reminders":
            return list(self.reminders)
        elif action == "stop_reminder":
            self.reminders = [
                item for item in self.reminders if item.get("id") != payload.get("id")
            ]
        return True

    def device_supports(self, feature: str) -> bool:
        return feature == "notify" and self.notify_feature

    def create_notification_audio(self, message: object) -> str:
        del message
        return self.notification_audio_url

    def notify(self, audio_url: str) -> object:
        if not self.notify_feature:
            raise BodyLost("StackChan did not advertise notify")
        if not audio_url.startswith("http://192.0.2."):
            raise ValueError("notification audio must be hosted by the Bot")
        self.push_actions.append(("notify", {"audio_url": audio_url}))
        return True

    def cancel_pending(self) -> None:
        """Drop only host-side queued targets; this does not cut servo torque."""
        self.pending_motion.clear()
        self.cancelled_motion_batches += 1

    def take_photo(self) -> bytes | None:
        self._require_link()
        if self.led_color != (168, 0, 0):
            raise AssertionError("camera capture refused because its indicator is off")
        self.calls.append(FakeToolCall("camera.take_photo", {}))
        self._camera_indicator_active = True
        self._camera_indicator_depth += 1
        try:
            return self.photo
        finally:
            self._camera_indicator_depth -= 1
            self._camera_indicator_active = False

    def send_avatar_frame(self, frame: bytes) -> None:
        self._require_link()
        self.avatar_frames.append(frame)

    def _require_link(self) -> None:
        if not self.connected:
            raise BodyLost("StackChan xiaozhi link was lost")


__all__ = ["FakeStackChanDeviceClient", "FakeToolCall"]
