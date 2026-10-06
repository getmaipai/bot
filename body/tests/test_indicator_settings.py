"""EYES-02: the seven robot-only settings keys."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from maipai_body.indicator.settings import (
    INDICATOR_KEYS,
    IndicatorSettings,
    eyes_settings_declaration,
    parse_settings,
)
from maipai_body.link.hello import settings_declaration

EXPECTED_KEYS = {
    "robot.indicator.enabled",
    "robot.indicator.brightness",
    "robot.indicator.night_brightness",
    "robot.indicator.night_start",
    "robot.indicator.night_end",
    "robot.indicator.sleep_eyes",
    "robot.indicator.alarm",
}
# The fields the existing declaration already uses, plus the two this order names.
ALLOWED_FIELDS = {
    "key",
    "type",
    "default",
    "scope",
    "label",
    "lives_in",
    "honoured_by",
    "needs",
    "range",
}


def test_exactly_the_seven_keys():
    declared = eyes_settings_declaration("eyes")
    assert {entry["key"] for entry in declared} == EXPECTED_KEYS
    assert len(declared) == 7
    assert set(INDICATOR_KEYS) == EXPECTED_KEYS


@pytest.mark.parametrize(("capability", "body"), [("eyes", "reachy"), ("light_ring", "build")])
def test_every_key_carries_the_required_fields_and_the_body_capability(capability, body):
    for entry in eyes_settings_declaration(capability):
        assert set(entry) <= ALLOWED_FIELDS, entry["key"]
        assert entry["label"] and entry["lives_in"]
        assert entry["scope"] == "device"
        assert entry["honoured_by"] == ["bot"]
        assert entry["needs"] == [capability], body


def test_keys_share_the_robot_device_page_of_the_existing_robot_only_key():
    declared = settings_declaration()
    robot_page = "Devices, this robot"
    for entry in declared:
        assert entry["lives_in"].startswith(robot_page), entry["key"]
    assert {entry["key"] for entry in declared} >= EXPECTED_KEYS


def test_sleep_eyes_declares_its_options_in_range():
    entry = next(e for e in eyes_settings_declaration("eyes") if e["key"].endswith("sleep_eyes"))
    assert entry["type"] == "select"
    assert entry["range"] == ["off", "dim"]
    assert "options" not in entry
    assert entry["default"] in entry["range"]


def test_defaults_parse_back_to_the_settings_dataclass_defaults():
    defaults = {e["key"]: e["default"] for e in eyes_settings_declaration("eyes")}
    assert parse_settings(defaults) == IndicatorSettings()


def test_out_of_range_or_malformed_values_fall_back_to_the_default():
    bad = {
        "robot.indicator.brightness": 9,
        "robot.indicator.night_brightness": "bright",
        "robot.indicator.night_start": "25:99",
        "robot.indicator.sleep_eyes": "strobe",
        "robot.indicator.enabled": "yes",
    }
    assert parse_settings(bad) == IndicatorSettings()


def test_the_declarations_validate_against_spec_settings_key_schema_when_available():
    """spec-v0.1.74's settings-key.schema.json lives in commons, which this clone
    cannot reach. Point MAIPAI_SPEC_SETTINGS_KEY_SCHEMA at the file to run it."""
    path = os.environ.get("MAIPAI_SPEC_SETTINGS_KEY_SCHEMA")
    if not path or not Path(path).is_file():
        pytest.skip("MAIPAI_SPEC_SETTINGS_KEY_SCHEMA is not set (commons spec not in this clone)")
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(Path(path).read_text())
    for capability in ("eyes", "light_ring"):
        for entry in eyes_settings_declaration(capability):
            jsonschema.validate(entry, schema)
