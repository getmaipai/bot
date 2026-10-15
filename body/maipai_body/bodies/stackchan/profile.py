"""StackChan capabilities and soft limits from the firmware research note."""

from maipai_body.hal.seam import AxisLimit, BodyProfile

_SOURCE = "M5Stack StackChan set_head_angles tool, design-stackchan-pieces-and-gaps-2026-10-14.md"
_DATE = "2026-10-14"

# Firmware accepts 100..1000. The profile's 150 soft ceiling is the only
# clamp applied by the Robot object until movement is measured on hardware.
HEAD_COMMAND_SPEED = 150
HEAD_SPEED_SOFT_MAX = 150
LED_COUNT = 12
LED_CHANNEL_MAX = 168

STACKCHAN_PROFILE = BodyProfile(
    id="stackchan",
    capabilities=[
        "lease",
        "estop",
        "head_pan_tilt",
        "light_ring",
        "speaker",
    ],
    axes=[
        AxisLimit(name="head_yaw", unit="deg", min=-128, max=128, source=_SOURCE, date=_DATE),
        AxisLimit(name="head_pitch", unit="deg", min=5, max=85, source=_SOURCE, date=_DATE),
        AxisLimit(
            name="head_speed",
            unit="firmware-units",
            min=100,
            max=HEAD_SPEED_SOFT_MAX,
            source=_SOURCE,
            date=_DATE,
        ),
    ],
    channels=["head", "leds", "audio"],
    sensors=[],
    physical_cuts=["power switch", "unplugging the robot"],
    speech_placement="pod",
    leased_motion={"head": ["set", "goto"]},
    safe_stop={"head": "hold"},
)

__all__ = [
    "HEAD_COMMAND_SPEED",
    "HEAD_SPEED_SOFT_MAX",
    "LED_CHANNEL_MAX",
    "LED_COUNT",
    "STACKCHAN_PROFILE",
]
