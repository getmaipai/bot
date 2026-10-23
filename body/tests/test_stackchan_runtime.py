"""Runtime wiring for StackChan behavior, using only local device fakes."""

from __future__ import annotations

import threading

import pytest

from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.hal.errors import EstopEngaged


def test_runtime_renders_idle_turn_and_tracking_through_robot_api():
    from maipai_body.app import StackChanBehavior

    device = FakeStackChanDeviceClient()
    behavior = StackChanBehavior(StackChanRobotAdapter(device).robot)
    try:
        behavior.render_primitive("settle")
        behavior.render_primitive("listen")
        behavior.render_turn_state("listening")
        behavior.render_turn_state("speaking")
        behavior.render_primitive("glance")
        assert device.avatar_frames
        assert any(call.name == "self.robot.set_head_angles" for call in device.calls)
        # The ring carries state through the light standard, never expression.
        assert not any(call.name.startswith("self.robot.set_led") for call in device.calls)
    finally:
        behavior.close()


def test_runtime_estop_blocks_motion_and_shutdown_joins_presence_worker():
    from maipai_body.app import StackChanBehavior

    device = FakeStackChanDeviceClient()
    behavior = StackChanBehavior(StackChanRobotAdapter(device).robot)
    behavior.start_presence(threading.Event())
    behavior.stop_presence()
    assert not behavior.presence_thread_alive
    behavior.robot.emergency_stop()
    with pytest.raises(EstopEngaged):
        behavior.render_primitive("glance")
    behavior.close()
    assert behavior.robot.lease_holder is None


def test_a_long_quiet_spell_drops_the_head_and_a_person_wakes_it():
    from maipai_body.app import StackChanBehavior

    device = FakeStackChanDeviceClient()
    behavior = StackChanBehavior(StackChanRobotAdapter(device).robot)
    try:
        start = behavior._rest._quiet_since
        assert behavior.rest_step(start + 1.0) == "awake"
        assert behavior.rest_step(start + 121.0) == "drowsy"
        frames = len(device.avatar_frames)
        assert behavior.rest_step(start + 200.0) == "drowsy"
        assert len(device.avatar_frames) == frames  # nothing new is sent for the same stage
        assert behavior.rest_step(start + 301.0) == "asleep"
        behavior._last_person_seen = start + 350.0
        assert behavior.rest_step(start + 351.0) == "awake"
    finally:
        behavior.close()
