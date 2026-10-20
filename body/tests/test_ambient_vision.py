"""BOT-SC-VISION-01: silent ambient capture, opt-in policy, text note only."""

from __future__ import annotations

import gc
import os
import weakref

import pytest

from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.ambient_vision import (
    AmbientVisionPolicy,
    AmbientVisionWorker,
)
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient, FakeToolCall
from maipai_body.hal.errors import EstopEngaged


class SilentFake(FakeStackChanDeviceClient):
    """The fake without the visible indicator guard, for silent capture."""

    def take_photo(self):
        self._require_link()
        self.calls.append(FakeToolCall("camera.take_photo", {}))
        return self.photo


def _camera_driver(device):
    robot = StackChanRobotAdapter(device).robot
    return robot, robot._driver("camera")


def test_visible_frame_still_lights_the_ring():
    device = SilentFake()
    device.photo = b"jpeg"
    _, camera = _camera_driver(device)

    assert camera.command("frame") == b"jpeg"

    led_calls = [call for call in device.calls if "set_led" in call.name]
    assert len(led_calls) >= 2
    take = [call for call in device.calls if call.name == "camera.take_photo"]
    assert len(take) == 1


def test_silent_frame_refused_when_ambient_vision_is_off():
    device = SilentFake()
    device.photo = b"jpeg"
    _, camera = _camera_driver(device)

    with pytest.raises(PermissionError, match="silent capture is off"):
        camera.command("frame", silent=True)

    assert not [call for call in device.calls if call.name == "camera.take_photo"]
    assert not [call for call in device.calls if "set_led" in call.name]


def test_silent_frame_returns_bytes_without_any_led_writes():
    device = SilentFake()
    device.photo = b"jpeg"
    _, camera = _camera_driver(device)
    camera.silent_capture_allowed = lambda: True

    assert camera.command("frame", silent=True) == b"jpeg"

    assert [call.name for call in device.calls] == ["camera.take_photo"]


def test_silent_frame_refused_while_estop_is_engaged():
    device = SilentFake()
    device.photo = b"jpeg"
    robot, camera = _camera_driver(device)
    camera.silent_capture_allowed = lambda: True
    robot.emergency_stop()

    with pytest.raises(EstopEngaged):
        camera.command("frame", silent=True)

    assert not [call for call in device.calls if call.name == "camera.take_photo"]


def test_frame_rejects_any_argument_other_than_silent():
    device = SilentFake()
    _, camera = _camera_driver(device)

    with pytest.raises(TypeError, match="camera.frame takes no arguments"):
        camera.command("frame", extra=1)
    with pytest.raises(TypeError, match="camera.frame takes no arguments"):
        camera.command("frame", b"bytes")
    with pytest.raises(TypeError, match="silent"):
        camera.command("frame", silent="yes")


def test_policy_never_captures_when_disabled():
    policy = AmbientVisionPolicy(enabled=lambda: False)

    assert policy.should_capture(0.0, funnel_idle_s=999.0, turn_active=False) is False
    assert policy.capture_on_demand_allowed(0.0, turn_active=False) is False


def test_policy_needs_the_funnel_idle_gate():
    policy = AmbientVisionPolicy(enabled=lambda: True)

    assert policy.should_capture(0.0, funnel_idle_s=59.9, turn_active=False) is False
    assert policy.should_capture(60.0, funnel_idle_s=60.0, turn_active=False) is True


def test_policy_blocks_during_turn_quiet_hours_or_child():
    for blocked in (
        {"turn_active": True},
        {"turn_active": False, "quiet_hours_active": True},
        {"turn_active": False, "child_present": True},
    ):
        policy = AmbientVisionPolicy(enabled=lambda: True)
        assert policy.should_capture(0.0, funnel_idle_s=999.0, **blocked) is False
        assert not policy._approved_at


def test_policy_enforces_the_gap_between_approvals():
    policy = AmbientVisionPolicy(enabled=lambda: True, min_gap_s=120.0)

    assert policy.should_capture(0.0, funnel_idle_s=999.0, turn_active=False) is True
    assert policy.should_capture(119.9, funnel_idle_s=999.0, turn_active=False) is False
    assert policy.should_capture(120.0, funnel_idle_s=999.0, turn_active=False) is True


def test_policy_enforces_the_hourly_cap_with_a_sliding_window():
    policy = AmbientVisionPolicy(enabled=lambda: True, min_gap_s=120.0, max_per_hour=20)

    for index in range(20):
        assert policy.should_capture(index * 120.0, funnel_idle_s=999.0, turn_active=False) is True
    assert policy.should_capture(2400.0, funnel_idle_s=999.0, turn_active=False) is False
    # the whole approved window has now slid past 3600 seconds
    assert policy.should_capture(5999.0, funnel_idle_s=999.0, turn_active=False) is True


def test_on_demand_ignores_the_idle_gate_but_counts_toward_the_cap():
    policy = AmbientVisionPolicy(enabled=lambda: True, min_gap_s=120.0, max_per_hour=2)

    assert policy.capture_on_demand_allowed(0.0, turn_active=True) is True
    assert policy.capture_on_demand_allowed(1.0, turn_active=False) is True
    assert policy.capture_on_demand_allowed(2.0, turn_active=False) is False
    # on-demand approvals block the ambient rule too, until the window slides
    assert policy.should_capture(3.0, funnel_idle_s=999.0, turn_active=False) is False
    assert policy.should_capture(3602.0, funnel_idle_s=999.0, turn_active=False) is True


class FakeCamera:
    def __init__(self, frame):
        self._frame = frame
        self.seen: list[tuple[str, dict[str, object]]] = []

    def command(self, verb, *args, **kwargs):
        self.seen.append((verb, dict(kwargs)))
        assert verb == "frame"
        assert kwargs == {"silent": True}
        return self._frame


class FrameBytes:
    """Weakref-capable frame stand-in; CPython cannot weakref bytes subclasses."""

    def __init__(self, data: bytes) -> None:
        self.data = data


def _worker(frame, describe, remember):
    camera = FakeCamera(frame)
    return camera, AmbientVisionWorker(camera, describe, remember)


def test_worker_requests_a_silent_frame():
    camera, worker = _worker(FrameBytes(b"img"), lambda frame: "a quiet room", lambda n: None)

    worker.run_once()

    assert camera.seen == [("frame", {"silent": True})]


def test_worker_remembers_the_truncated_note():
    remembered: list[str] = []
    frame = FrameBytes(b"img")
    _, worker = _worker(frame, lambda frame: "x" * 300, remembered.append)

    note = worker.run_once()

    assert note == "x" * 280
    assert remembered == ["x" * 280]


def test_worker_does_not_keep_the_frame():
    remembered: list[str] = []
    frame = FrameBytes(b"img")
    camera, worker = _worker(frame, lambda frame: "a quiet room", remembered.append)
    ref = weakref.ref(frame)

    worker.run_once()
    camera._frame = None
    del frame
    gc.collect()

    assert ref() is None
    assert remembered == ["a quiet room"]


def test_worker_writes_nothing_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    frame = FrameBytes(b"img")
    _, worker = _worker(frame, lambda frame: "a quiet room", lambda note: None)

    worker.run_once()

    assert os.listdir(tmp_path) == []


def test_worker_drops_the_frame_when_describe_raises():
    def describe(frame):
        raise RuntimeError("vision model unavailable")

    remembered: list[str] = []
    frame = FrameBytes(b"img")
    _, worker = _worker(frame, describe, remembered.append)

    with pytest.raises(RuntimeError, match="vision model unavailable"):
        worker.run_once()

    assert remembered == []


def test_worker_returns_none_without_a_frame_or_without_a_note():
    _, no_frame = _worker(None, lambda frame: "should not run", lambda n: None)

    assert no_frame.run_once() is None

    remembered: list[str] = []
    _, blank = _worker(FrameBytes(b"img"), lambda frame: "   ", remembered.append)

    assert blank.run_once() is None
    assert remembered == []
