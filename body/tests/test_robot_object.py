"""Robot API promises exercised through the configurable recorded fake body."""

from __future__ import annotations

import json
import time

import pytest

from maipai_body.bodies.fake import FakeBody
from maipai_body.hal.errors import (
    BodyLost,
    DeadlineExpired,
    EstopEngaged,
    NotPermitted,
    NotSupported,
)
from maipai_body.hal.seam import AxisLimit, BodyProfile, HeadPose
from maipai_body.robot import Robot, RobotStateFrame
from maipai_body.robot.api import default_spec_dir, load_robot_api


def test_robot_parts_are_exposed_only_when_the_profile_declares_the_capability():
    body = FakeBody(capabilities=["head_pan_tilt", "lease", "estop"])

    assert body.robot.capabilities == frozenset({"head_pan_tilt", "lease", "estop"})
    assert body.robot.head is not None
    with pytest.raises(NotSupported) as raised:
        _ = body.robot.battery
    assert raised.value.part == "battery"
    assert raised.value.capability == "battery_readout"
    assert "battery" in str(raised.value)
    assert "Use a body profile" in raised.value.fix


def test_head_command_needs_a_lease_and_returns_the_profile_clamped_pose():
    body = FakeBody(capabilities=["head_pan_tilt", "lease", "estop"])
    requested = HeadPose(pitch=1.0, roll=-1.0, yaw=2.0)

    with pytest.raises(NotPermitted, match="acquire"):
        body.robot.head.set(pose=requested)

    body.robot.lease.acquire("person", "remote")
    applied = body.robot.head.set(pose=requested)

    assert applied["pose"].pitch == 0.5
    assert applied["pose"].roll == -0.4
    assert applied["pose"].yaw == 1.2
    assert body.commands[-1].kwargs["pose"] == applied["pose"]


def test_emergency_stop_bypasses_the_lease_then_blocks_motion_until_released():
    body = FakeBody(capabilities=["head_pan_tilt", "estop", "lease"])

    assert body.robot.emergency_stop() is True
    with pytest.raises(EstopEngaged, match="release the emergency stop"):
        body.robot.head.set(pose=HeadPose())

    body.robot.estop.release()
    body.robot.lease.acquire("expression", "renderer")
    body.robot.head.set(pose=HeadPose())
    assert body.robot.estop_engaged is False


def test_motion_profile_must_declare_both_lease_and_emergency_stop():
    with pytest.raises(ValueError, match="lacks estop, lease"):
        FakeBody(capabilities=["head_pan_tilt"])


def test_lease_priorities_allow_safety_to_preempt_a_lower_priority_holder():
    body = FakeBody(capabilities=["lease"])
    body.robot.lease.acquire("idle", "idle-loop")

    lease = body.robot.lease.acquire("safety", "safety-gate")

    assert lease.holder == "safety-gate"
    assert body.robot.lease_holder == "safety-gate"
    with pytest.raises(NotPermitted, match="cannot take control"):
        body.robot.lease.acquire("idle", "late-idle")


def test_base_drive_requires_a_live_deadline_and_stops_when_it_has_passed():
    body = FakeBody(capabilities=["base", "lease", "estop"])

    with pytest.raises(ValueError, match="monotonic deadline"):
        body.robot.base.drive(vx=0.2, vy=0.0, wz=0.0)
    with pytest.raises(DeadlineExpired, match="told to stop"):
        body.robot.base.drive(vx=0.2, vy=0.0, wz=0.0, deadline=time.monotonic() - 1.0)
    assert body.commands[-1].part == "base"
    assert body.commands[-1].verb == "stop"


def test_appendage_and_base_commands_return_clamped_positional_and_keyword_values():
    body = FakeBody(capabilities=["appendages", "base", "lease", "estop"])
    body.robot.lease.acquire("person", "remote")

    appendage = body.robot.appendages.set("left", 1.0)
    drive = body.robot.base.drive(vx=1.0, vy=0.0, wz=1.0, deadline=time.monotonic() + 5.0)

    assert appendage == ("left", 0.6)
    assert drive["vx"] == 0.2
    assert drive["wz"] == 0.5
    assert body.commands[-2].args == ("left", 0.6)
    assert body.commands[-1].kwargs["vx"] == 0.2


def test_recorded_state_frames_replay_with_monotonic_stamps_and_increasing_sequences():
    body = FakeBody(capabilities=["state_feed"])

    frames = list(body.robot.state.stream())

    assert all(isinstance(frame, RobotStateFrame) for frame in frames)
    assert [frame.seq for frame in frames] == [1, 2, 3]
    assert [frame.parts["battery"]["level"] for frame in frames] == [0.82, 0.81, 0.81]
    assert all(left.t_received_ns < right.t_received_ns for left, right in zip(frames, frames[1:]))


def test_lost_body_engages_fail_safe_and_refuses_followup_motion():
    body = FakeBody(capabilities=["head_pan_tilt", "lease", "estop"])

    class LostHead:
        def command(self, *_args, **_kwargs):
            raise BodyLost("the fake link dropped")

    drivers = dict(body.robot._drivers)
    drivers["head"] = LostHead()
    from maipai_body.robot import Robot

    robot = Robot(body.profile, drivers, body.api)
    robot.lease.acquire("person", "remote")
    with pytest.raises(BodyLost, match="link dropped"):
        robot.head.set(pose=HeadPose())

    assert robot.estop_engaged is True
    assert any(command.part == "estop" and command.verb == "engage" for command in body.commands)
    with pytest.raises(EstopEngaged):
        robot.head.set(pose=HeadPose())


def test_whole_robot_lifecycle_verbs_translate_to_the_declared_power_part():
    body = FakeBody(capabilities=["power"])

    assert body.robot.wake() == "awake"
    assert body.robot.shutdown() == "off"
    assert [(command.part, command.verb) for command in body.commands] == [
        ("power", "wake"),
        ("power", "shutdown"),
    ]


def test_vocabulary_profile_runs_without_a_vendor_specific_robot_assumption():
    spec_dir = default_spec_dir()
    vocab = json.loads((spec_dir / "vocab" / "capabilities.json").read_text())
    api = load_robot_api(spec_dir)
    capabilities = set(vocab["capabilities"])
    selected = {"head_6dof", "appendages", "lease", "estop"}
    assert selected <= capabilities
    profile = BodyProfile(
        id="six_axis_mobile_body",
        capabilities=sorted(selected),
        axes=[
            AxisLimit(
                name=name,
                unit="rad",
                min=-0.5,
                max=0.5,
                source="test profile",
                date="2026-10-15",
            )
            for name in ("head_pitch", "head_roll", "head_yaw", "antenna_left", "antenna_right")
        ],
        channels=["head", "appendages"],
        sensors=[],
        physical_cuts=[],
        speech_placement="robot",
    )

    class Driver:
        def __init__(self, part: str):
            self.part = part
            self.commands = []

        def command(self, verb: str, *args, **kwargs):
            self.commands.append((verb, args, kwargs))
            return True

    drivers = {part: Driver(part) for part in ("head", "appendages", "lease", "estop")}
    robot = Robot(profile, drivers, api)
    assert robot.capabilities == frozenset(selected)
    lease = robot.lease.acquire("person", "remote")
    assert lease.holder == "remote"
    robot.head.set(pose=HeadPose(pitch=0.2, roll=-0.1, yaw=0.3))
    robot.appendages.set("left", 0.4)
    assert robot.emergency_stop() is True
    assert robot.estop_engaged is True
    with pytest.raises(NotSupported) as raised:
        _ = robot.camera
    assert raised.value.part == "camera"
    assert raised.value.capability == "camera"
