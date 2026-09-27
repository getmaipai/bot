"""The profile's declared shape: capabilities, axes, and the speech placement."""

from maipai_body.bodies.reachy_mini.profile import PROFILE

# The ids the design record's section 2 and the commons item BODY-VOCAB-01
# name for this body. BODY-VOCAB-01 has not landed in `commons/spec` yet
# (checked at spec-v0.1.48); once it does, this list should pin against
# `spec/vocab/capabilities.json` at the tag `body/pyproject.toml` names,
# and this test becomes the one that catches drift.
_EXPECTED_CAPABILITIES = {
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
}


def test_capability_list_matches_the_vocabulary() -> None:
    assert set(PROFILE.capabilities) == _EXPECTED_CAPABILITIES


def test_physical_cuts_are_empty_for_this_body() -> None:
    assert PROFILE.physical_cuts == []


def test_speech_placement_is_the_v0_1_baseline() -> None:
    assert PROFILE.speech_placement == "speech_pod"


def test_every_axis_names_its_source_and_date() -> None:
    for axis in PROFILE.axes:
        assert axis.source, f"{axis.name} has no source"
        assert axis.date, f"{axis.name} has no date"
        assert axis.min < axis.max, f"{axis.name} has an inverted range"
