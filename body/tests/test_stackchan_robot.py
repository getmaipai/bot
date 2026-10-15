"""StackChan profile and xiaozhi adapter promises exercised without hardware."""

from __future__ import annotations

import math

import pytest

from maipai_body.bodies.stackchan import STACKCHAN_PROFILE, StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.hal.errors import BodyLost, EstopEngaged, NotSupported
from maipai_body.hal.seam import HeadPose
from maipai_body.robot import Robot, load_robot_api


def test_stackchan_profile_declares_available_parts_without_advertising_camera():
    assert STACKCHAN_PROFILE.id == "stackchan"
    assert {"head_pan_tilt", "lease", "estop", "light_ring", "screen"} <= set(
        STACKCHAN_PROFILE.capabilities
    )
    assert {"touch", "imu", "battery_readout", "mic", "speaker"} <= set(
        STACKCHAN_PROFILE.capabilities
    )
    assert "camera" not in STACKCHAN_PROFILE.capabilities
    assert STACKCHAN_PROFILE.axis("head_yaw").min == -128
    assert STACKCHAN_PROFILE.axis("head_yaw").max == 128
    assert STACKCHAN_PROFILE.axis("head_pitch").min == 5
    assert STACKCHAN_PROFILE.axis("head_pitch").max == 85


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


def test_missing_camera_raises_not_supported_with_a_fix():
    robot = Robot(STACKCHAN_PROFILE, {}, api=load_robot_api())

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
    with pytest.raises(EstopEngaged, match="release the emergency stop"):
        robot.head.goto(pose=HeadPose(pitch=math.radians(45)))
    assert not any(call.name == "self.robot.set_head_angles" for call in device.calls)


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
    assert not any(call.name == "self.robot.set_head_angles" for call in device.calls)
