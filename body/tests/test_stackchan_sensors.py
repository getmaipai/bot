"""StackChan sensor reads against the fake xiaozhi MCP peer."""

from __future__ import annotations

import pytest

from maipai_body.bodies.stackchan import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.profile import SENSOR_MCP_TOOLS
from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient
from maipai_body.hal.errors import BodyLost, NotSupported


def test_battery_state_reads_pinned_read_only_mcp_tool():
    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot

    assert robot.battery.level == 75
    assert robot.battery.charging is False
    assert robot.battery.state == {"percent": 75, "charging": False}
    assert [call.name for call in device.calls] == [
        "self.battery.get_status",
        "self.battery.get_status",
        "self.battery.get_status",
    ]


def test_profile_records_sensor_tool_names_shapes_sources_and_dates():
    assert SENSOR_MCP_TOOLS["battery"]["name"] == "self.battery.get_status"
    assert SENSOR_MCP_TOOLS["battery"]["result"] == {
        "percent": "integer 0..100",
        "charging": "boolean",
    }
    assert SENSOR_MCP_TOOLS["battery"]["source"]
    assert SENSOR_MCP_TOOLS["battery"]["date"] == "2026-10-15"
    assert SENSOR_MCP_TOOLS["touch"]["name"] is None
    assert SENSOR_MCP_TOOLS["imu"]["name"] is None


def test_xiaozhi_device_client_issues_battery_tools_call():
    class FakeMcpPeer:
        def __init__(self):
            self.calls = []

        def call_device_tool(self, name, arguments, *, timeout):
            self.calls.append((name, arguments, timeout))
            return {"percent": 64, "charging": True}

    peer = FakeMcpPeer()
    client = XiaozhiDeviceClient(peer)

    assert client.get_battery_status() == {"percent": 64, "charging": True}
    assert len(peer.calls) == 1
    assert peer.calls[0][0:2] == ("self.battery.get_status", {})


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({"percent": 101, "charging": False}, "invalid battery status"),
        ({"percent": 75, "charging": 0}, "invalid battery status"),
    ],
)
def test_invalid_battery_tool_results_map_to_body_lost(response, message):
    device = FakeStackChanDeviceClient()
    device.battery_status = response
    robot = StackChanRobotAdapter(device).robot

    with pytest.raises(BodyLost, match=message):
        _ = robot.battery.state


def test_battery_timeout_maps_to_body_lost():
    device = FakeStackChanDeviceClient()
    device.battery_error = TimeoutError("MCP reply timed out")
    robot = StackChanRobotAdapter(device).robot

    with pytest.raises(BodyLost, match="battery"):
        _ = robot.battery.state


@pytest.mark.parametrize(
    ("part", "capability", "reason"),
    [
        ("touch", "touch", "no touch read tool"),
        ("imu", "imu", "no IMU read tool"),
    ],
)
def test_touch_and_imu_remain_explicitly_unsupported(part, capability, reason):
    robot = StackChanRobotAdapter(FakeStackChanDeviceClient()).robot

    with pytest.raises(NotSupported, match=reason) as raised:
        getattr(robot, part).read()

    assert raised.value.part == part
    assert raised.value.capability == capability
