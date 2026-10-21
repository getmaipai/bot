"""Host-side StackChan companion tests for the dance, events and Wi-Fi tools.

The firmware side of these calls is patches 020, 021 and 023; nothing here
has run on a unit, so every test drives a recording fake instead of a link.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from maipai_body.bodies.stackchan.companion import (
    DANCES,
    EVENT_KINDS,
    DeviceEvent,
    SavedNetwork,
    StackChanCompanion,
)
from maipai_body.hal.errors import BodyLost, NotSupported


class _RecordingCall:
    """Records each tool call and returns canned results or raises canned errors."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.results: dict[str, object] = {}
        self.raisers: dict[str, Exception] = {}

    def __call__(self, tool_name: str, arguments: dict[str, object]) -> object:
        self.calls.append((tool_name, dict(arguments)))
        if tool_name in self.raisers:
            raise self.raisers[tool_name]
        return self.results.get(tool_name)


def _names(calls: list[tuple[str, dict[str, object]]]) -> list[str]:
    return [name for name, _ in calls]


def test_dances_and_event_kinds_export_the_supported_sets():
    assert DANCES == frozenset({"happy", "robot", "panic", "look_around"})
    assert EVENT_KINDS == frozenset(
        {
            "head_touch",
            "head_swipe_forward",
            "head_swipe_back",
            "shake",
            "level_changed",
            "touch_down",
            "touch_up",
            "face_pressed",
            "face_clicked",
            "gesture",
            "gesture_ignored",
            "click_ignored",
            "head_touch_stats",
            "stop_word",
            "heap_stats",
            "stack_stats",
            "boot",
        }
    )


def test_device_event_and_saved_network_are_frozen():
    with pytest.raises(FrozenInstanceError):
        DeviceEvent(kind="head_touch", at_ms=1).kind = "shake"
    with pytest.raises(FrozenInstanceError):
        SavedNetwork(index=0, ssid="Home").ssid = "Guest"


def test_dance_sends_the_selected_name_and_records_the_call():
    call = _RecordingCall()
    call.results["self.robot.dance"] = True
    companion = StackChanCompanion(call)

    companion.dance("robot")

    assert call.calls == [("self.robot.dance", {"name": "robot"})]


def test_dance_rejects_an_unknown_name_before_calling():
    call = _RecordingCall()
    companion = StackChanCompanion(call)

    with pytest.raises(ValueError, match="not a known dance"):
        companion.dance("breakdance")

    assert call.calls == []


def test_dance_raises_body_lost_when_the_tool_refuses():
    call = _RecordingCall()
    call.results["self.robot.dance"] = False
    companion = StackChanCompanion(call)

    with pytest.raises(BodyLost, match="did not start the dance"):
        companion.dance("happy")


def test_companion_lets_the_device_not_supported_propagate():
    call = _RecordingCall()
    call.raisers["self.robot.dance"] = NotSupported("dance is unavailable", part="robot")
    companion = StackChanCompanion(call)

    with pytest.raises(NotSupported):
        companion.dance("happy")


def test_stop_dance_calls_the_stop_tool_with_no_arguments():
    call = _RecordingCall()
    companion = StackChanCompanion(call)

    companion.stop_dance()

    assert call.calls == [("self.robot.stop_dance", {})]


def test_poll_events_parses_a_json_string():
    call = _RecordingCall()
    call.results["self.robot.get_events"] = (
        '[{"kind": "head_touch", "at_ms": 1234}, {"kind": "shake", "at_ms": 5678}]'
    )
    companion = StackChanCompanion(call)

    events = companion.poll_events()

    assert events == [
        DeviceEvent(kind="head_touch", at_ms=1234),
        DeviceEvent(kind="shake", at_ms=5678),
    ]


def test_poll_events_accepts_an_already_parsed_list():
    call = _RecordingCall()
    call.results["self.robot.get_events"] = [{"kind": "head_swipe_forward", "at_ms": 9}]
    companion = StackChanCompanion(call)

    assert companion.poll_events() == [DeviceEvent(kind="head_swipe_forward", at_ms=9)]


def test_poll_events_keeps_unknown_kinds_for_forward_compatibility():
    call = _RecordingCall()
    call.results["self.robot.get_events"] = [{"kind": "face_plant", "at_ms": 1}]
    companion = StackChanCompanion(call)

    assert companion.poll_events() == [DeviceEvent(kind="face_plant", at_ms=1)]


def test_poll_events_skips_malformed_json_and_returns_empty():
    call = _RecordingCall()
    call.results["self.robot.get_events"] = "{not valid json"
    companion = StackChanCompanion(call)

    assert companion.poll_events() == []


def test_poll_events_skips_items_missing_fields():
    call = _RecordingCall()
    call.results["self.robot.get_events"] = [
        {"kind": "head_touch"},
        {"at_ms": 7},
        {"kind": "shake", "at_ms": 42},
        "garbage",
    ]
    companion = StackChanCompanion(call)

    assert companion.poll_events() == [DeviceEvent(kind="shake", at_ms=42)]


def test_poll_events_returns_empty_when_the_device_sends_nothing():
    companion = StackChanCompanion(_RecordingCall())

    assert companion.poll_events() == []


def test_wifi_list_parses_a_json_string():
    call = _RecordingCall()
    call.results["self.wifi.list_saved"] = '[{"index": 0, "ssid": "Home"}]'
    companion = StackChanCompanion(call)

    assert companion.wifi_list() == [SavedNetwork(index=0, ssid="Home")]


def test_wifi_list_accepts_an_already_parsed_list():
    call = _RecordingCall()
    call.results["self.wifi.list_saved"] = [{"index": 1, "ssid": "Guest"}]
    companion = StackChanCompanion(call)

    assert companion.wifi_list() == [SavedNetwork(index=1, ssid="Guest")]


def test_wifi_add_sends_ssid_and_password():
    call = _RecordingCall()
    call.results["self.wifi.add"] = True
    companion = StackChanCompanion(call)

    companion.wifi_add("Home", "s3cret-pass")

    assert call.calls == [("self.wifi.add", {"ssid": "Home", "password": "s3cret-pass"})]


def test_wifi_add_allows_an_empty_password_for_an_open_network():
    call = _RecordingCall()
    call.results["self.wifi.add"] = True
    companion = StackChanCompanion(call)

    companion.wifi_add("Open", "")

    assert call.calls == [("self.wifi.add", {"ssid": "Open", "password": ""})]


def test_wifi_add_rejects_an_empty_ssid():
    call = _RecordingCall()
    companion = StackChanCompanion(call)

    with pytest.raises(ValueError, match="ssid"):
        companion.wifi_add("", "x")

    assert call.calls == []


def test_wifi_add_rejects_an_ssid_longer_than_thirty_two_bytes():
    call = _RecordingCall()
    companion = StackChanCompanion(call)

    with pytest.raises(ValueError, match="ssid"):
        companion.wifi_add("a" * 33, "x")

    assert call.calls == []


def test_wifi_add_counts_ssid_length_in_utf_8_bytes():
    call = _RecordingCall()
    companion = StackChanCompanion(call)

    with pytest.raises(ValueError, match="ssid"):
        companion.wifi_add("é" * 17, "x")

    assert call.calls == []


def test_wifi_add_accepts_a_thirty_two_byte_utf_8_ssid():
    call = _RecordingCall()
    call.results["self.wifi.add"] = True
    companion = StackChanCompanion(call)

    companion.wifi_add("é" * 16, "x")

    assert call.calls == [("self.wifi.add", {"ssid": "é" * 16, "password": "x"})]


def test_wifi_add_rejects_a_password_longer_than_sixty_three_bytes():
    call = _RecordingCall()
    companion = StackChanCompanion(call)

    with pytest.raises(ValueError, match="password"):
        companion.wifi_add("Home", "p" * 64)

    assert call.calls == []


def test_wifi_add_accepts_a_sixty_three_byte_password():
    call = _RecordingCall()
    call.results["self.wifi.add"] = True
    companion = StackChanCompanion(call)

    companion.wifi_add("Home", "p" * 63)

    assert call.calls == [("self.wifi.add", {"ssid": "Home", "password": "p" * 63})]


def test_wifi_add_raises_body_lost_when_the_tool_refuses():
    call = _RecordingCall()
    call.results["self.wifi.add"] = False
    companion = StackChanCompanion(call)

    with pytest.raises(BodyLost, match="did not save the network"):
        companion.wifi_add("Home", "s3cret-pass")


def test_wifi_add_never_puts_the_password_in_an_exception_message():
    call = _RecordingCall()
    call.raisers["self.wifi.add"] = BodyLost("the device refused to save the network")
    companion = StackChanCompanion(call)

    with pytest.raises(BodyLost) as caught:
        companion.wifi_add("Home", "s3cret-pass")

    assert "s3cret-pass" not in str(caught.value)
    assert call.calls == [("self.wifi.add", {"ssid": "Home", "password": "s3cret-pass"})]


def test_wifi_forget_sends_the_saved_index():
    call = _RecordingCall()
    call.results["self.wifi.forget"] = True
    companion = StackChanCompanion(call)

    companion.wifi_forget(2)

    assert call.calls == [("self.wifi.forget", {"index": 2})]


def test_wifi_forget_raises_body_lost_when_the_index_is_missing():
    call = _RecordingCall()
    call.results["self.wifi.forget"] = False
    companion = StackChanCompanion(call)

    with pytest.raises(BodyLost, match="no saved network at that position"):
        companion.wifi_forget(5)


def test_wifi_forget_rejects_a_boolean_index():
    call = _RecordingCall()
    companion = StackChanCompanion(call)

    with pytest.raises(ValueError, match="index"):
        companion.wifi_forget(True)

    assert call.calls == []


def test_wifi_switch_sends_the_saved_index():
    call = _RecordingCall()
    call.results["self.wifi.switch"] = True
    companion = StackChanCompanion(call)

    companion.wifi_switch(1)

    assert call.calls == [("self.wifi.switch", {"index": 1})]


def test_wifi_switch_raises_body_lost_when_the_index_is_missing():
    call = _RecordingCall()
    call.results["self.wifi.switch"] = False
    companion = StackChanCompanion(call)

    with pytest.raises(BodyLost, match="no saved network at that position"):
        companion.wifi_switch(3)


def test_wifi_switch_rejects_a_negative_index():
    call = _RecordingCall()
    companion = StackChanCompanion(call)

    with pytest.raises(ValueError, match="index"):
        companion.wifi_switch(-1)

    assert call.calls == []


def test_wifi_switch_rejects_a_boolean_index():
    call = _RecordingCall()
    companion = StackChanCompanion(call)

    with pytest.raises(ValueError, match="index"):
        companion.wifi_switch(False)

    assert call.calls == []


def test_wifi_switch_to_switches_the_saved_network_by_ssid():
    call = _RecordingCall()
    call.results["self.wifi.list_saved"] = [
        {"index": 0, "ssid": "Home"},
        {"index": 1, "ssid": "Guest"},
    ]
    call.results["self.wifi.switch"] = True
    companion = StackChanCompanion(call)

    assert companion.wifi_switch_to("Guest") is True

    assert _names(call.calls) == ["self.wifi.list_saved", "self.wifi.switch"]
    assert call.calls[1] == ("self.wifi.switch", {"index": 1})


def test_wifi_switch_to_returns_false_without_calling_switch_when_not_saved():
    call = _RecordingCall()
    call.results["self.wifi.list_saved"] = [{"index": 0, "ssid": "Home"}]
    companion = StackChanCompanion(call)

    assert companion.wifi_switch_to("Office") is False

    assert _names(call.calls) == ["self.wifi.list_saved"]


def test_the_real_device_client_hands_its_tool_call_to_the_companion():
    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient

    calls: list[tuple[str, dict]] = []

    class _Server:
        def call_device_tool(self, name, arguments, timeout):
            calls.append((name, arguments))
            return True

    client = XiaozhiDeviceClient.__new__(XiaozhiDeviceClient)
    client.server = _Server()
    client.timeout = 1.0
    client.companion().dance("happy")
    assert calls == [("self.robot.dance", {"name": "happy"})]


def test_diagnostic_events_keep_their_small_fields():
    companion = StackChanCompanion(
        lambda name, args: [
            {"kind": "touch_down", "at_ms": 5, "x": 12, "y": 34},
            {"kind": "gesture_ignored", "at_ms": 6, "why": "boot"},
            {"kind": "shake", "at_ms": 7, "x": 1},
        ]
    )
    down, ignored, shake = companion.poll_events()
    assert down.extra == {"x": 12, "y": 34} and ignored.extra == {"why": "boot"}
    assert shake.extra is None
