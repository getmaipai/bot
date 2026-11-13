"""Per-pixel LED tool and camera indicator protection tests."""

from __future__ import annotations

import pytest

from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.profile import LED_COUNT, STACKCHAN_PROFILE


def _updates(colors):
    return [{"index": index, "rgb": color} for index, color in enumerate(colors)]


def test_leds_many_sends_twelve_individual_colors():
    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    robot.lease.acquire("person", "led-test")
    colors = [(index, index + 1, index + 2) for index in range(LED_COUNT)]

    robot.leds.many(_updates(colors))

    assert list(device.led_colors) == colors
    assert device.calls[-1].name == "self.robot.set_led_colors"
    assert STACKCHAN_PROFILE.capabilities.count("light_ring") == 1


def test_leds_many_preserves_validation_error_shapes():
    robot = StackChanRobotAdapter(FakeStackChanDeviceClient()).robot
    robot.lease.acquire("person", "led-test")
    updates = _updates([(1, 2, 3)] * LED_COUNT)

    with pytest.raises(Exception, match="Include all 12"):
        robot.leds.many(updates[:-1])
    duplicate = list(updates)
    duplicate[-1] = dict(duplicate[0])
    with pytest.raises(ValueError, match="appears more than once"):
        robot.leds.many(duplicate)
    invalid = list(updates)
    invalid[0] = {"index": 0, "rgb": [169, 0, 0]}
    with pytest.raises(ValueError, match="LED channels must be integers"):
        robot.leds.many(invalid)


def test_a_photo_writes_no_pixel_itself_and_raises_the_cue_before_the_capture():
    """The ring has one writer, the light service; the adapter only raises the cue, and does it
    before the capture (a privacy rule), so the service has already lit the ring."""
    order: list[str] = []

    class DuringCapture(FakeStackChanDeviceClient):
        def take_photo(self):
            order.append("capture")
            assert not [call for call in self.calls if "led" in call.name]
            return b"jpeg"

    device = DuringCapture()
    adapter = StackChanRobotAdapter(device)
    adapter.robot.lease.acquire("person", "camera-test")
    adapter.robot._driver("camera").cue_sink = lambda active: order.append(f"cue {active}")
    import asyncio

    assert asyncio.run(adapter.take_photo()) == b"jpeg"
    assert order == ["cue True", "capture", "cue False"]
    assert device.led_colors == ((0, 0, 0),) * LED_COUNT
