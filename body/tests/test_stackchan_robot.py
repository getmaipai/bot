"""StackChan profile and xiaozhi adapter promises exercised without hardware."""

from __future__ import annotations

import concurrent.futures
import math
from pathlib import Path

import pytest

from maipai_body.bodies.stackchan import STACKCHAN_PROFILE, StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.measure import write_results
from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient
from maipai_body.hal.errors import (
    BodyLost,
    EstopEngaged,
    NotPermitted,
    NotSupported,
    OutOfEnvelope,
)
from maipai_body.hal.seam import HeadPose
from maipai_body.robot import Robot, load_robot_api


def test_stackchan_profile_declares_available_parts_including_camera():
    assert STACKCHAN_PROFILE.id == "stackchan"
    assert {"head_pan_tilt", "lease", "estop", "light_ring", "speaker"} <= set(
        STACKCHAN_PROFILE.capabilities
    )
    assert not set(STACKCHAN_PROFILE.capabilities) & {
        "screen",
        "touch",
        "imu",
        "battery_readout",
        "mic",
    }
    assert "camera" in STACKCHAN_PROFILE.capabilities
    assert STACKCHAN_PROFILE.axis("head_yaw").min == -128
    assert STACKCHAN_PROFILE.axis("head_yaw").max == 128
    assert STACKCHAN_PROFILE.axis("head_pitch").min == 5
    assert STACKCHAN_PROFILE.axis("head_pitch").max == 85
    assert STACKCHAN_PROFILE.axis("head_speed").max == 150
    assert STACKCHAN_PROFILE.axis("head_speed").unit == "firmware-units"


def test_every_stackchan_declared_capability_resolves_to_a_driver():
    robot = StackChanRobotAdapter(FakeStackChanDeviceClient()).robot
    assert robot.lease is not None
    assert robot.estop is not None
    for part_id in {"head", "leds", "audio", "camera"}:
        assert robot._driver(part_id) is not None


def test_head_goto_clamps_in_radians_and_sends_the_applied_pose_at_bounded_speed():
    device = FakeStackChanDeviceClient()
    adapter = StackChanRobotAdapter(device)
    robot = adapter.robot
    robot.lease.acquire("person", "test")

    applied = robot.head.goto(
        pose=HeadPose(yaw=math.radians(150), pitch=math.radians(0)), duration=0.2
    )

    assert device.head_angles == {"yaw": 128, "pitch": 5}
    assert device.calls[-1].name == "self.robot.set_head_angles"
    assert device.calls[-1].arguments == {"yaw": 128, "pitch": 5, "speed": 150}
    assert applied == {"yaw": 128, "pitch": 5, "speed": 150}


def test_head_none_axes_keep_the_minus_9999_firmware_sentinel_out_of_range():
    device = FakeStackChanDeviceClient()
    adapter = StackChanRobotAdapter(device)
    adapter.robot.lease.acquire("person", "sentinel-regression")

    adapter._set_head_angles(-9999, 45, 150)

    assert device.head_angles == {"yaw": -128, "pitch": 45}
    assert device.calls[-1].arguments == {"yaw": -128, "pitch": 45, "speed": 150}


@pytest.mark.parametrize(
    ("part", "capability"),
    [("battery", "battery_readout"), ("touch", "touch"), ("imu", "imu")],
)
def test_unverified_sensor_parts_are_not_supported_with_unit_arrival_action(part, capability):
    robot = StackChanRobotAdapter(FakeStackChanDeviceClient()).robot

    with pytest.raises(NotSupported) as raised:
        getattr(robot, part).read()

    assert raised.value.part == part
    assert raised.value.capability == capability
    assert "unit measurement kit" in raised.value.fix
    assert "Fix:" in str(raised.value)


def test_unit_arrival_kit_writes_simulator_results_as_unverified(tmp_path: Path):
    device = FakeStackChanDeviceClient()
    output = tmp_path / "run" / "measurements.json"

    result = write_results(device, output, source="simulator")

    saved = __import__("json").loads(output.read_text())
    assert result["unit_verified"] is False
    assert saved["measurements"]["servo_limits_deg"]["pitch"] == [5, 85]
    assert saved["measurements"]["camera"]["fps"] == 5.0
    assert saved["measurements"]["aec"]["quality"] == "simulated"
    assert saved["measurements"]["battery"]["level_percent"] == 75
    assert saved["measurements"]["base_mcp_tools"]


def test_stackchan_service_adapter_requires_callers_lease_across_sequence():
    device = FakeStackChanDeviceClient()
    adapter = StackChanRobotAdapter(device)
    with pytest.raises(NotPermitted, match="needs a control lease"):
        adapter._set_head_angles(10, 45, 150)
    lease = adapter.robot.lease.acquire("person", "sequence")
    adapter._set_head_angles(10, 45, 150)
    assert adapter.robot.lease_holder == lease.holder


def test_missing_camera_raises_not_supported_with_a_fix():
    profile = STACKCHAN_PROFILE.model_copy(
        update={"capabilities": [cap for cap in STACKCHAN_PROFILE.capabilities if cap != "camera"]}
    )
    robot = Robot(profile, {}, api=load_robot_api())

    with pytest.raises(NotSupported) as raised:
        _ = robot.camera

    assert raised.value.part == "camera"
    assert raised.value.capability == "camera"
    assert "Use a body profile" in raised.value.fix
    assert "Fix:" in str(raised.value)


def test_software_estop_latches_and_cancels_host_queued_targets():
    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    device.pending_motion.extend(["target-1", "target-2"])

    robot.emergency_stop()

    assert robot.estop.engaged is True
    assert device.pending_motion == []
    assert device.cancelled_motion_batches >= 1
    assert [call.name for call in device.calls[-2:]] == [
        "self.robot.get_head_angles",
        "self.robot.set_head_angles",
    ]
    assert device.calls[-1].arguments == {"yaw": 0, "pitch": 45, "speed": 150}
    command_count = len(device.calls)
    with pytest.raises(EstopEngaged, match="release the emergency stop"):
        robot.head.goto(pose=HeadPose(pitch=math.radians(45)))
    assert len(device.calls) == command_count
    assert robot.last_safe_stop == ()


def test_estop_latches_and_reports_body_lost_if_current_angles_cannot_be_read():
    class LostReadDevice(FakeStackChanDeviceClient):
        def get_head_angles(self):
            raise BodyLost("head-angle read failed")

    robot = StackChanRobotAdapter(LostReadDevice()).robot

    with pytest.raises(BodyLost, match="head-angle read failed"):
        robot.emergency_stop()

    assert robot.estop_engaged is True
    assert robot.estop.engaged is True
    assert robot.last_safe_stop == ("head.hold",)


def test_lost_link_latches_estop_and_sends_no_more_head_angles():
    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    robot.lease.acquire("person", "test")
    device.pending_motion.append("queued target")
    device.connected = False

    with pytest.raises(BodyLost, match="link was lost"):
        robot.head.goto(pose=HeadPose(pitch=math.radians(45)))

    assert robot.estop.engaged is True
    assert device.pending_motion == []
    assert device.cancelled_motion_batches >= 1
    with pytest.raises(EstopEngaged):
        robot.head.goto(pose=HeadPose(pitch=math.radians(45)))


def test_stackchan_estop_safe_stop_uses_supported_head_hold_verb():
    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    robot.emergency_stop()
    assert robot.last_safe_stop == ()
    assert device.cancelled_motion_batches >= 1


def test_camera_photo_and_stream_indicator_turn_on_and_off_on_success_and_failure():
    from maipai_body.bodies.stackchan.avatar_frames import AvatarCommand, decode_frame

    device = FakeStackChanDeviceClient()
    device.photo = b"\xff\xd8sample"
    robot = StackChanRobotAdapter(device).robot
    assert robot.camera.frame() == device.photo
    assert [call.arguments for call in device.calls if call.name == "self.robot.set_led_color"][
        -2:
    ] == [
        {"red": 168, "green": 0, "blue": 0},
        {"red": 0, "green": 0, "blue": 0},
    ]
    robot.camera.stream()
    assert decode_frame(device.avatar_frames[-1]).command == AvatarCommand.START_CAMERA_STREAM
    assert device.led_color == (168, 0, 0)
    robot.camera.stream(enabled=False)
    assert decode_frame(device.avatar_frames[-1]).payload == b"\x00"
    assert device.led_color == (0, 0, 0)

    robot.camera.stream()
    robot._driver("camera").disconnected()
    assert device.led_color == (0, 0, 0)

    device.connected = False
    with pytest.raises(BodyLost):
        robot.camera.frame()
    assert device.led_color == (0, 0, 0)


def test_camera_stream_is_refused_while_estopped():
    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    robot.emergency_stop()
    with pytest.raises(EstopEngaged, match="camera stream refused"):
        robot.camera.stream()
    assert [call.name for call in device.calls] == [
        "self.robot.get_head_angles",
        "self.robot.set_head_angles",
    ]


def test_unconfirmed_xiaozhi_head_command_latches_estop():
    class NoReplyServer:
        def call_device_tool(self, name, arguments, *, timeout):
            raise TimeoutError("device reply timed out")

        def cancel_device_calls(self, name):
            return None

    robot = StackChanRobotAdapter(XiaozhiDeviceClient(NoReplyServer())).robot
    robot.lease.acquire("person", "test")

    with pytest.raises(BodyLost, match="did not complete"):
        robot.head.goto(pose=HeadPose(pitch=math.radians(45)))

    assert robot.estop.engaged is True
    with pytest.raises(EstopEngaged):
        robot.head.goto(pose=HeadPose(pitch=math.radians(45)))


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ConnectionError("link unavailable"), BodyLost),
        (TimeoutError("reply expired"), BodyLost),
        (concurrent.futures.CancelledError(), EstopEngaged),
        (RuntimeError("target angle out of range"), OutOfEnvelope),
        (RuntimeError("unsupported tool"), NotSupported),
    ],
)
def test_every_device_tool_maps_failures_to_robot_seam_errors(error, expected):
    class FailingServer:
        def call_device_tool(self, _name, _arguments, *, timeout):
            raise error

        def cancel_device_calls(self, _name):
            return None

    device = XiaozhiDeviceClient(FailingServer())
    with pytest.raises(expected):
        device.set_volume(35)


def test_invalid_device_head_angles_are_reported_as_body_lost():
    class InvalidAnglesServer:
        def call_device_tool(self, _name, _arguments, *, timeout):
            return {"yaw": "0", "pitch": 45}

        def cancel_device_calls(self, _name):
            return None

    with pytest.raises(BodyLost, match="invalid head angles"):
        XiaozhiDeviceClient(InvalidAnglesServer()).get_head_angles()
