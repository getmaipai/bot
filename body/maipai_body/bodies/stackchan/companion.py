"""Host companion for the new StackChan firmware tools.

The device side of these calls is StackChan firmware patch 020 (dance),
patch 021 (head touch events) and patch 023 (Wi-Fi). Nothing here has run
on a unit yet; the offline tests drive a recording fake, not a real link.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from maipai_body.hal.errors import BodyLost

DANCES = frozenset({"happy", "robot", "panic", "look_around"})
# Screen-touch diagnostics from firmware patch 046: logged by the host, never a reason to react.
DIAGNOSTIC_KINDS = frozenset(
    {
        "touch_down",
        "touch_up",
        "face_pressed",
        "face_clicked",
        "gesture",
        "gesture_ignored",
        "click_ignored",
        "head_touch_stats",
    }
)
EVENT_KINDS = (
    frozenset({"head_touch", "head_swipe_forward", "head_swipe_back", "shake", "level_changed"})
    | DIAGNOSTIC_KINDS
)

_NO_NETWORK_AT_INDEX = "no saved network at that position, list the networks again"


@dataclass(frozen=True)
class DeviceEvent:
    kind: str
    at_ms: int
    # level_changed only: the speaker and screen levels the person set on the unit's panel.
    volume: int | None = None
    brightness: int | None = None
    # Diagnostic events only: the other small fields the unit sent (x, y, dir, why, ready).
    extra: dict[str, object] | None = None


@dataclass(frozen=True)
class SavedNetwork:
    index: int
    ssid: str


def _percent(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        return None
    return value


class StackChanCompanion:
    """Validate and translate the new StackChan firmware tool calls."""

    def __init__(self, call: Callable[[str, dict[str, object]], object]) -> None:
        self._call = call

    def dance(self, name: str) -> None:
        if not isinstance(name, str) or name not in DANCES:
            raise ValueError(
                f"dance {name!r} is not a known dance; use one of {', '.join(sorted(DANCES))}"
            )
        result = self._call("self.robot.dance", {"name": name})
        if result is False:
            raise BodyLost("StackChan did not start the dance. Check that it is awake and retry.")

    def stop_dance(self) -> None:
        self._call("self.robot.stop_dance", {})

    def poll_events(self) -> list[DeviceEvent]:
        items = self._as_list(self._call("self.robot.get_events", {}))
        if items is None:
            return []
        events: list[DeviceEvent] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            at_ms = item.get("at_ms")
            if not isinstance(kind, str):
                continue
            if isinstance(at_ms, bool) or not isinstance(at_ms, int):
                continue
            events.append(
                DeviceEvent(
                    kind=kind,
                    at_ms=at_ms,
                    volume=_percent(item.get("volume")),
                    brightness=_percent(item.get("brightness")),
                    extra=(
                        {
                            key: value
                            for key, value in item.items()
                            if key not in {"kind", "at_ms"} and isinstance(value, (int, str, bool))
                        }
                        if kind in DIAGNOSTIC_KINDS or kind.startswith("head_")
                        else None
                    )
                    or None,
                )
            )
        return events

    def wifi_list(self) -> list[SavedNetwork]:
        items = self._as_list(self._call("self.wifi.list_saved", {}))
        if items is None:
            return []
        networks: list[SavedNetwork] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            ssid = item.get("ssid")
            if isinstance(index, bool) or not isinstance(index, int):
                continue
            if not isinstance(ssid, str):
                continue
            networks.append(SavedNetwork(index=index, ssid=ssid))
        return networks

    def wifi_add(self, ssid: str, password: str) -> None:
        if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32:
            raise ValueError("ssid must be 1 to 32 UTF-8 bytes; shorten the network name")
        if not isinstance(password, str) or len(password.encode("utf-8")) > 63:
            raise ValueError("wifi password must be at most 63 UTF-8 bytes; use a shorter password")
        result = self._call("self.wifi.add", {"ssid": ssid, "password": password})
        if result is False:
            raise BodyLost(
                "StackChan did not save the network. Check the name and password and retry."
            )

    def wifi_forget(self, index: int) -> None:
        self._require_index(index)
        result = self._call("self.wifi.forget", {"index": index})
        if result is False:
            raise BodyLost(_NO_NETWORK_AT_INDEX)

    def wifi_switch(self, index: int) -> None:
        self._require_index(index)
        result = self._call("self.wifi.switch", {"index": index})
        if result is False:
            raise BodyLost(_NO_NETWORK_AT_INDEX)

    def wifi_switch_to(self, ssid: str) -> bool:
        for network in self.wifi_list():
            if network.ssid == ssid:
                self.wifi_switch(network.index)
                return True
        return False

    @staticmethod
    def _require_index(index: object) -> int:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError(
                "network index must be an integer at or above zero; list the saved "
                "networks and use a position from that list"
            )
        return index

    @staticmethod
    def _as_list(result: object) -> list[object] | None:
        if isinstance(result, list):
            return result
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
            except ValueError:
                return None
            if isinstance(parsed, list):
                return parsed
        return None


__all__ = ["DANCES", "EVENT_KINDS", "DeviceEvent", "SavedNetwork", "StackChanCompanion"]
