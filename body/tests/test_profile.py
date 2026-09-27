"""Tests named for the promises RM-01 makes about the Reachy Mini profile."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE

BODY_ROOT = Path(__file__).parent.parent / "maipai_body"
PROFILE_PATH = BODY_ROOT / "bodies" / "reachy_mini" / "profile.py"


def _declared_limit_literals() -> set[str]:
    """Every min/max numeric literal profile.py passes to an AxisLimit(...) call."""
    tree = ast.parse(PROFILE_PATH.read_text())
    literals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "AxisLimit":
            for kw in node.keywords:
                if kw.arg in ("min", "max") and isinstance(kw.value, ast.Constant):
                    literals.add(repr(float(kw.value.value)))
    return literals


def test_profile_is_the_sole_source_of_limits():
    """A numeric limit the profile declares appears nowhere else in the package."""
    literals = _declared_limit_literals()
    assert literals, "expected profile.py to declare at least one AxisLimit"

    offending: list[str] = []
    for path in BODY_ROOT.rglob("*.py"):
        if path == PROFILE_PATH:
            continue
        text = path.read_text()
        for literal in literals:
            pattern = re.compile(rf"(?<![\d.]){re.escape(literal)}(?![\d.])")
            if pattern.search(text):
                offending.append(f"{path}: {literal}")

    assert not offending, f"a profile limit leaked outside profile.py: {offending}"


def test_capabilities_match_the_vocabulary_ids():
    """The declared capability ids match the design record's list exactly.

    This is the test BODY-VOCAB-01 (commons' RM-00) will pin to the spec
    tag once that item lands; today it pins to
    ``docs/dev/design-reachy-mini-2026-09-27.md`` section 2's own list,
    since ``commons/spec/vocab/capabilities.json`` does not carry these
    body-profile ids yet.
    """
    expected = {
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
    assert set(REACHY_MINI_PROFILE.capabilities) == expected


def test_physical_cuts_are_empty_for_this_body():
    """This body has no physical mute or camera shutter (design record section 8)."""
    assert REACHY_MINI_PROFILE.physical_cuts == []


def test_speech_placement_is_pod_tier_for_v0_1():
    """The v0.1 baseline speech placement (design record decision 4)."""
    assert REACHY_MINI_PROFILE.speech_placement == "pod"
