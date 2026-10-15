"""StackChan capabilities and soft limits from the firmware research note."""

from maipai_body.hal.seam import AxisLimit, BodyProfile

_SOURCE = "M5Stack StackChan set_head_angles tool, design-stackchan-pieces-and-gaps-2026-10-14.md"
_DATE = "2026-10-14"

# Slow, bounded servo commands reduce the movement size before unit measurements exist.
HEAD_COMMAND_SPEED = 150
HEAD_SPEED_MIN = 100
HEAD_SPEED_MAX = 1000
LED_COUNT = 12
LED_CHANNEL_MAX = 168

STACKCHAN_PROFILE = BodyProfile(
    id="stackchan",
    capabilities=[
        "connection",
        "lease",
        "estop",
        "head_pan_tilt",
        "light_ring",
        "screen",
        "touch",
        "imu",
        "battery_readout",
        "mic",
        "speaker",
    ],
    axes=[
        AxisLimit(name="head_yaw", unit="deg", min=-128, max=128, source=_SOURCE, date=_DATE),
        AxisLimit(name="head_pitch", unit="deg", min=5, max=85, source=_SOURCE, date=_DATE),
    ],
    channels=["head", "display", "leds", "audio"],
    sensors=["touch", "imu", "battery", "microphone"],
    physical_cuts=["power switch", "unplugging the robot"],
    speech_placement="pod",
)

__all__ = [
    "HEAD_COMMAND_SPEED",
    "HEAD_SPEED_MIN",
    "HEAD_SPEED_MAX",
    "LED_CHANNEL_MAX",
    "LED_COUNT",
    "STACKCHAN_PROFILE",
]
