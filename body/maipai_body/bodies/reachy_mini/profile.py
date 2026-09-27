"""The Reachy Mini profile: the one place this body's limits are named.

Sources, read on the date given:

- Daemon-clamped head and body limits (pitch, roll, head yaw, body yaw, the
  head-to-body yaw delta): `docs/dev/design-reachy-mini-2026-09-27.md`
  section 1, itself read from Pollen's SDK and daemon docs
  (https://huggingface.co/docs/reachy_mini) on 2026-09-27. That record notes
  one Pollen page states body yaw at +/-180 degrees against another at
  +/-160 degrees, unverified; +/-160 is the value this profile carries,
  as the design record decided.
- Antenna range: the installed `reachy-mini` SDK's own URDF
  (`reachy_mini/descriptions/reachy_mini/urdf/robot.urdf`, joints
  `left_antenna` and `right_antenna`), reachy-mini 1.11.0, read 2026-09-27:
  both joints declare `lower="-3.141592653589793" upper="3.141592653589793"`
  radians, the XL330 servo's full turn.

BODY-VOCAB-01 (`commons` spec workspace) will later declare these
capability ids in `spec/vocab/capabilities.json` and this profile will pin
against that tag; until then the ids are copied here from the design
record's section 2, matched by `test_capabilities_match_vocabulary` below.
"""

from maipai_body.hal.seam import Axis, BodyProfile, Channel, Sensor

_SOURCE_DATE = "2026-09-27"
_DESIGN_RECORD = "docs/dev/design-reachy-mini-2026-09-27.md section 1"
_SDK_URDF = "reachy-mini 1.11.0 URDF (left_antenna, right_antenna joints)"

PROFILE = BodyProfile(
    id="reachy_mini",
    capabilities=[
        "head_6dof",
        "roll",
        "antennas",
        "body_yaw",
        "camera",
        "mic",
        "speaker",
        "doa",
        "state_feed",
        "imu",
        "moves_recorded",
        "speech_pod",
    ],
    axes=[
        Axis(
            name="head_pitch",
            unit="deg",
            min=-40.0,
            max=40.0,
            source=_DESIGN_RECORD,
            date=_SOURCE_DATE,
        ),
        Axis(
            name="head_roll",
            unit="deg",
            min=-40.0,
            max=40.0,
            source=_DESIGN_RECORD,
            date=_SOURCE_DATE,
        ),
        Axis(
            name="head_yaw",
            unit="deg",
            min=-180.0,
            max=180.0,
            source=_DESIGN_RECORD,
            date=_SOURCE_DATE,
        ),
        Axis(
            name="body_yaw",
            unit="deg",
            min=-160.0,
            max=160.0,
            source=_DESIGN_RECORD,
            date=_SOURCE_DATE,
        ),
        Axis(
            name="head_to_body_yaw_delta",
            unit="deg",
            min=-65.0,
            max=65.0,
            source=_DESIGN_RECORD,
            date=_SOURCE_DATE,
        ),
        Axis(
            name="antennas",
            unit="deg",
            min=-180.0,
            max=180.0,
            source=_SDK_URDF,
            date=_SOURCE_DATE,
        ),
    ],
    channels=[
        Channel(name="head", kind="6dof"),
        Channel(name="antennas", kind="pair"),
        Channel(name="body_yaw", kind="yaw"),
    ],
    sensors=[
        Sensor(name="state_feed", kind="pose_stream"),
        Sensor(name="camera", kind="rgb"),
        Sensor(name="mic", kind="array"),
        Sensor(name="doa", kind="direction_of_arrival"),
        Sensor(name="imu", kind="accel_gyro_quat"),
    ],
    physical_cuts=[],
    speech_placement="speech_pod",
)
