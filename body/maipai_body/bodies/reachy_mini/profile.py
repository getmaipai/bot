"""The Reachy Mini body's one declaration: what it has, never how it is driven.

This is the only file in the repo where this body's numeric limits
appear (a test greps the package for that). Every limit below names its
source and the date it was recorded or last verified, per
``docs/dev/design-reachy-mini-2026-09-27.md`` section 1's own table and
section 13's "officially supported" bar.

Capability ids anticipate the body-capability vocabulary commons will
declare under BODY-VOCAB-01 (backlog item RM-00, not yet landed in
``commons/spec/vocab/`` as of this writing: that file still only carries
the platform-plan-3.2 generic list). The ids used here are the ones
``docs/dev/design-reachy-mini-2026-09-27.md`` section 2 and the bot
backlog's RM-00 entry already name (``head_6dof``, ``roll``,
``antennas``, ``body_yaw``, ``camera``, ``mic``, ``speaker``, ``doa``,
``state_feed``, ``imu``, ``moves_recorded``, ``speech_pod``); when
RM-00 lands and pins a tag, this list is reconciled against it rather
than invented twice (the test named for that promise is
``tests/test_profile.py::test_capabilities_match_the_vocabulary_ids``).
"""

from __future__ import annotations

from maipai_body.hal.seam import AxisLimit, BodyProfile

_DESIGN_RECORD = (
    "docs/dev/design-reachy-mini-2026-09-27.md section 1 (Pollen's own docs, read 2026-09-27)"
)
_DAEMON_URDF = (
    "the running daemon's /api/kinematics/urdf, right_antenna/left_antenna joint "
    "limits (reachy-mini daemon 1.11.0, verified live against the simulator, 2026-09-27)"
)

REACHY_MINI_PROFILE = BodyProfile(
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
        AxisLimit(
            name="head_pitch",
            unit="deg",
            min=-40.0,
            max=40.0,
            source=_DESIGN_RECORD,
            date="2026-09-27",
        ),
        AxisLimit(
            name="head_roll",
            unit="deg",
            min=-40.0,
            max=40.0,
            source=_DESIGN_RECORD,
            date="2026-09-27",
        ),
        AxisLimit(
            name="head_yaw",
            unit="deg",
            min=-180.0,
            max=180.0,
            source=_DESIGN_RECORD,
            date="2026-09-27",
        ),
        AxisLimit(
            name="body_yaw",
            unit="deg",
            min=-160.0,
            max=160.0,
            source=(
                _DESIGN_RECORD
                + " (one Pollen page states +/-180 degrees instead; the design record "
                "flags this as conflicting and unverified, and this profile takes the "
                "more conservative figure until M-R2 measures the daemon's own clamp)"
            ),
            date="2026-09-27",
        ),
        AxisLimit(
            name="head_to_body_yaw_delta",
            unit="deg",
            min=-65.0,
            max=65.0,
            source=_DESIGN_RECORD,
            date="2026-09-27",
        ),
        AxisLimit(
            name="antenna_left",
            unit="rad",
            min=-3.141592653589793,
            max=3.141592653589793,
            source=_DAEMON_URDF,
            date="2026-09-27",
        ),
        AxisLimit(
            name="antenna_right",
            unit="rad",
            min=-3.141592653589793,
            max=3.141592653589793,
            source=_DAEMON_URDF,
            date="2026-09-27",
        ),
    ],
    channels=["head", "antennas", "body_yaw"],
    sensors=["state_feed", "camera", "doa_array", "imu"],
    physical_cuts=[],
    speech_placement="pod",
)
