"""StackChan capabilities and soft limits from the firmware research note."""

from maipai_body.hal.seam import AxisLimit, BodyProfile

_SOURCE = "M5Stack StackChan set_head_angles tool, design-stackchan-pieces-and-gaps-2026-10-14.md"
_DATE = "2026-10-14"
_BATTERY_SOURCE = (
    "MaiPai firmware patch 010 self.battery.get_status, reading existing HAL battery methods; "
    "patch 009 makes AXP2101 I2C read failures return a safe zero"
)
_BATTERY_DATE = "2026-10-15"
SENSOR_MCP_TOOLS = {
    "battery": {
        "name": "self.battery.get_status",
        "result": {"percent": "integer 0..100", "charging": "boolean"},
        "source": _BATTERY_SOURCE,
        "date": _BATTERY_DATE,
    },
    "touch": {
        "name": None,
        "result": None,
        "source": "Pinned M5Stack/xiaozhi MCP tool inventory has no touch read tool",
        "date": "2026-10-15",
    },
    "imu": {
        "name": None,
        "result": None,
        "source": "Pinned M5Stack/xiaozhi MCP tool inventory has no IMU read tool",
        "date": "2026-10-15",
    },
}

# Firmware accepts 100..1000: the number sets a spring's stiffness (k = 10 + (speed/1000)^2 *
# 640, main/stackchan/motion/servo.cpp), so a move eases in and the tail is slow. Measured on the
# unit 2026-11-12: at 120 a 60 degree turn made two thirds of its way in 2 s and settled by about
# 6 s. The ceiling was 150 until that measurement; 400 (k about 112, under a second to settle)
# lets a turn toward a person be quick while the idle and the look-around moves stay slow.
HEAD_COMMAND_SPEED = 150
HEAD_SPEED_SOFT_MAX = 400
LED_COUNT = 12
LED_CHANNEL_MAX = 168
# Level, the head's resting pose, in degrees. The pitch servo only travels UP from level: its limit
# is 3 to 87 degrees (firmware hal_servo.cpp, angleLimit 30..870 in tenths), M5's tool text says
# "Neutral position is pitch 0" and "90 is up", and the firmware itself returns to pitch 0 as its
# default pose. The middle of the 5..85 profile range (45) is therefore 45 degrees UP, which is
# why the head always looked at the ceiling. If 5 does not look level by eye, change this number.
CENTRE_PITCH_DEG = 5
# The head's travel, the one place the numbers live (the axes below use them, and so does anything
# that adds up commanded poses: a pose past these is clamped by the Robot, so a sum that keeps
# growing no longer matches where the head is, live log 2026-11-13 09:05: a follow reached 252).
HEAD_YAW_LIMIT_DEG = 128
HEAD_PITCH_MAX_DEG = 85
HEAD_PITCH_UP_LIMIT_DEG = HEAD_PITCH_MAX_DEG - CENTRE_PITCH_DEG  # degrees up from level
# How many degrees the camera sees side to side and top to bottom: a face at an edge is half
# of it away. Measured on the unit 2026-11-12 22:12 (a swing of yaw 0, +60, 0, -60 with the head
# tilted up 50, eight seconds a pose, a frame kept at every look): 60 degrees of yaw moved the
# ceiling lamp three quarters of the frame once the servo had settled, so the picture is about
# 80 degrees across; the vertical span follows the 4:3 picture.
FOLLOW_YAW_SPAN_DEG = 80
FOLLOW_PITCH_SPAN_DEG = 60
# +yaw turns the camera toward the picture's right (the same swing: at +60 the content moved
# left, at -60 right). The sign lives here so the one measurement is the one place to change.
FOLLOW_YAW_SIGN = 1.0
EXPRESSION_YAW_FRACTION = 0.12
EXPRESSION_PITCH_FRACTION = 0.08

STACKCHAN_PROFILE = BodyProfile(
    id="stackchan",
    capabilities=[
        "lease",
        "estop",
        "head_pan_tilt",
        "light_ring",
        "speaker",
        "camera",
        "battery_readout",
    ],
    axes=[
        AxisLimit(
            name="head_yaw",
            unit="deg",
            min=-HEAD_YAW_LIMIT_DEG,
            max=HEAD_YAW_LIMIT_DEG,
            source=_SOURCE,
            date=_DATE,
        ),
        AxisLimit(
            name="head_pitch", unit="deg", min=5, max=HEAD_PITCH_MAX_DEG, source=_SOURCE, date=_DATE
        ),
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
    sensors=["battery"],
    physical_cuts=["power switch", "unplugging the robot"],
    speech_placement="pod",
    leased_motion={
        "head": ["set", "goto"],
        "audio": ["speaker.speak", "listen_window"],
        "alerts": ["show"],
        "reminders": ["create_reminder", "get_reminders", "stop_reminder"],
    },
    safe_stop={"head": "hold"},
)

# Opt-in only. The runtime also requires the active device hello feature.
STACKCHAN_NOTIFY_ENABLED = False

__all__ = [
    "HEAD_COMMAND_SPEED",
    "HEAD_PITCH_UP_LIMIT_DEG",
    "HEAD_YAW_LIMIT_DEG",
    "HEAD_SPEED_SOFT_MAX",
    "LED_CHANNEL_MAX",
    "LED_COUNT",
    "SENSOR_MCP_TOOLS",
    "STACKCHAN_PROFILE",
    "STACKCHAN_NOTIFY_ENABLED",
]
