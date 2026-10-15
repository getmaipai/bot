"""The replay body's synthetic limits and default capability subset."""

from maipai_body.hal.seam import AxisLimit, BodyProfile

_SOURCE = "synthetic fake-body limits for deterministic robot replay"
_DATE = "2026-10-14"

FAKE_PROFILE = BodyProfile(
    id="fake_replay",
    capabilities=[
        "connection",
        "power",
        "estop",
        "lease",
        "head_pan_tilt",
        "battery_readout",
        "state_feed",
    ],
    axes=[
        AxisLimit(name="head_pitch", unit="rad", min=-0.5, max=0.5, source=_SOURCE, date=_DATE),
        AxisLimit(name="head_roll", unit="rad", min=-0.4, max=0.4, source=_SOURCE, date=_DATE),
        AxisLimit(name="head_yaw", unit="rad", min=-1.2, max=1.2, source=_SOURCE, date=_DATE),
        AxisLimit(name="antenna_left", unit="rad", min=-0.6, max=0.6, source=_SOURCE, date=_DATE),
        AxisLimit(name="antenna_right", unit="rad", min=-0.6, max=0.6, source=_SOURCE, date=_DATE),
        AxisLimit(name="base_vx", unit="m/s", min=-0.2, max=0.2, source=_SOURCE, date=_DATE),
        AxisLimit(name="base_vy", unit="m/s", min=-0.2, max=0.2, source=_SOURCE, date=_DATE),
        AxisLimit(name="base_wz", unit="rad/s", min=-0.5, max=0.5, source=_SOURCE, date=_DATE),
    ],
    channels=["head", "power"],
    sensors=["battery", "state_feed"],
    physical_cuts=[],
    speech_placement="robot",
    leased_motion={
        "head": ["set", "goto"],
        "appendages": ["set", "goto"],
        "base": ["drive", "goto", "turn"],
    },
    safe_stop={"base": "stop", "head": "hold"},
    axis_map={"appendages.left": "antenna_left", "appendages.right": "antenna_right"},
)
