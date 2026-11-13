"""StackChan expression and camera privacy guarantees, using offline fakes."""

from __future__ import annotations

import asyncio

import pytest

from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.profile import STACKCHAN_PROFILE
from maipai_body.expression.cue import Cue, Phase
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.expression.primitives import PRIMITIVE_NAMES
from maipai_body.expression.renderers import renderer_for
from maipai_body.expression.suppression import SuppressionContext
from maipai_body.hal.errors import EstopEngaged


def test_stackchan_expression_maps_account_for_all_cues_and_primitives():
    from maipai_body.bodies.stackchan.expression_map import (
        CUE_FACE_MAP,
        PRIMITIVE_BODY_MAP,
        REPLY_MOOD_FACE_MAP,
        UNSUPPORTED_PRIMITIVES,
    )

    assert set(CUE_FACE_MAP) == {"listening", "thinking", "speaking", "reply_mood"}
    assert set(PRIMITIVE_BODY_MAP) | set(UNSUPPORTED_PRIMITIVES) == set(PRIMITIVE_NAMES)
    assert all(reason for reason in UNSUPPORTED_PRIMITIVES.values())
    assert all(
        target.expression in {"neutral", "listening", "thinking"}
        for target in CUE_FACE_MAP.values()
    )
    assert set(REPLY_MOOD_FACE_MAP.values()) <= {
        "neutral",
        "happy",
        "angry",
        "sad",
        "doubt",
        "sleepy",
        "surprised",
    }


def test_stackchan_renderer_clamps_every_motion_target_to_profile_limits():
    import maipai_body.expression  # noqa: F401

    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    robot.lease.acquire("expression", "stackchan-expression")
    render = renderer_for("stackchan")
    for primitive in PRIMITIVE_NAMES:
        try:
            render(primitive, robot._driver("head").expression_device, STACKCHAN_PROFILE)
        except NotImplementedError:
            continue
    for call in device.calls:
        if call.name == "self.robot.set_head_angles":
            values = call.arguments
            if values["yaw"] is not None:
                assert (
                    STACKCHAN_PROFILE.axis("head_yaw").min
                    <= values["yaw"]
                    <= STACKCHAN_PROFILE.axis("head_yaw").max
                )
            if values["pitch"] is not None:
                assert (
                    STACKCHAN_PROFILE.axis("head_pitch").min
                    <= values["pitch"]
                    <= STACKCHAN_PROFILE.axis("head_pitch").max
                )


def test_expression_engine_selects_stackchan_renderer_and_estop_discards_motion():
    import maipai_body.expression  # noqa: F401

    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    robot.lease.acquire("expression", "stackchan-expression")
    engine = ExpressionEngine(robot._driver("head"), STACKCHAN_PROFILE)
    try:
        result = engine.handle(Cue(phase=Phase.HEARD, cue_seq=1), SuppressionContext())
        assert result.rendered
        robot.emergency_stop()
        count = len(device.calls)
        with pytest.raises(EstopEngaged):
            render = renderer_for("stackchan")
            render("nod", robot._driver("head").expression_device, STACKCHAN_PROFILE)
        assert len(device.calls) == count
    finally:
        engine.close()


def test_camera_photo_raises_the_cue_first_and_lowers_it_on_capture_error():
    events: list[str] = []

    class GuardedCamera(FakeStackChanDeviceClient):
        def take_photo(self):
            assert events == ["cue up"], "camera capture began without its cue"
            events.append("capture")
            return super().take_photo()

    device = GuardedCamera()
    adapter = StackChanRobotAdapter(device)
    adapter.robot._driver("camera").cue_sink = lambda active: events.append(
        "cue up" if active else "cue down"
    )
    device.photo = b"jpeg"
    assert asyncio.run(adapter.take_photo()) == b"jpeg"
    assert events == ["cue up", "capture", "cue down"]

    events.clear()

    class FailingCamera(GuardedCamera):
        def take_photo(self):
            super().take_photo()
            raise RuntimeError("capture failed")

    failing = StackChanRobotAdapter(FailingCamera())
    failing.robot._driver("camera").cue_sink = adapter.robot._driver("camera").cue_sink
    with pytest.raises(RuntimeError, match="capture failed"):
        asyncio.run(failing.take_photo())
    assert events == ["cue up", "capture", "cue down"]


def test_thinking_and_attention_faces_never_read_as_doubt_or_sadness():
    # Owner, 2026-10-20: the thinking face looked confused or disgusted. The firmware doubt face
    # draws one flat eye with a raised brow and a wavy mouth; sad draws a brow and a flat mouth.
    from maipai_body.bodies.stackchan.expression_map import (
        CUE_FACE_MAP,
        PRIMITIVE_BODY_MAP,
        REPLY_MOOD_FACE_MAP,
    )

    assert CUE_FACE_MAP["thinking"].expression == "thinking"  # its own face, patch 110
    assert CUE_FACE_MAP["listening"].expression == "listening"
    for name in ("listen", "glance", "tilt", "attend", "settle"):
        assert PRIMITIVE_BODY_MAP[name].face in {"neutral", "happy", None}, name
    assert REPLY_MOOD_FACE_MAP["doubt"] == "neutral"
    assert REPLY_MOOD_FACE_MAP["wry"] == "neutral"
