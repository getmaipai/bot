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
        self.calls: list[FakeToolCall] = []
        self.pending_motion: list[object] = []
        self.cancelled_motion_batches = 0

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
        arguments = {"red": red, "green": green, "blue": blue}
        self.calls.append(FakeToolCall("self.robot.set_led_color", arguments))
        return arguments

    def set_volume(self, volume: int) -> dict[str, int]:
        self._require_link()
        self.volume = volume
        arguments = {"volume": volume}
        self.calls.append(FakeToolCall("self.audio_speaker.set_volume", arguments))
        return arguments

    def cancel_pending(self) -> None:
        """Drop only host-side queued targets; this does not cut servo torque."""
        self.pending_motion.clear()
        self.cancelled_motion_batches += 1

    def _require_link(self) -> None:
        if not self.connected:
            raise BodyLost("StackChan xiaozhi link was lost")


__all__ = ["FakeStackChanDeviceClient", "FakeToolCall"]
