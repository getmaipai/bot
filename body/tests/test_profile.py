"""Tests named for the promises RM-01 makes about the Reachy Mini profile."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

from maipai_body.bodies.reachy_mini.profile import (
    REACHY_MINI_PROFILE,
    profile_for_eyes,
)

BODY_ROOT = Path(__file__).parent.parent / "maipai_body"
PROFILE_PATH = BODY_ROOT / "bodies" / "reachy_mini" / "profile.py"
SPEC_DIR = Path(os.environ.get("MAIPAI_SPEC_DIR", ""))
SPEC_FIXTURES = SPEC_DIR / "fixtures" / "records"


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
    """The profile declares only ids in the pinned shared vocabulary."""
    capabilities = json.loads((SPEC_DIR / "vocab" / "capabilities.json").read_text())[
        "capabilities"
    ]
    assert set(REACHY_MINI_PROFILE.capabilities) <= set(capabilities)


def _device_model():
    model_path = SPEC_DIR / "gen" / "py" / "device_schema.py"
    module_spec = importlib.util.spec_from_file_location("spec_device_schema", model_path)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module.Device


def _fixture(name: str) -> dict:
    assert SPEC_DIR.is_dir(), "the check gate must set MAIPAI_SPEC_DIR to spec-v0.1.76"
    return json.loads((SPEC_FIXTURES / name).read_text())


def test_reachy_profiles_match_the_pinned_spec_fixtures():
    """The base and Eyes-fitted profiles match their shared Device fixtures."""
    base = _fixture("device.robot-reachy-mini.example.json")
    with_eyes = _fixture("device.robot-reachy-mini-eyes.example.json")
    device_model = _device_model()

    assert set(REACHY_MINI_PROFILE.capabilities) == set(base["capabilities"])
    eyes = profile_for_eyes(SimpleNamespace(spec=lambda: SimpleNamespace(connected=True)))
    assert set(eyes.capabilities) == set(with_eyes["capabilities"])
    assert "eyes" not in base["capabilities"]
    assert "eyes" in with_eyes["capabilities"]
    device_model.model_validate(base)
    device_model.model_validate(with_eyes)


def test_maipai_build_spec_fixture_validates_with_pinned_device_model():
    """The other body fixture shipped with BODY-VOCAB-01 remains valid."""
    device_model = _device_model()
    fixture = _fixture("device.robot-maipai-build.example.json")
    vocab = json.loads((SPEC_DIR / "vocab" / "capabilities.json").read_text())["capabilities"]
    assert set(fixture["capabilities"]) <= set(vocab)
    device_model.model_validate(fixture)


def test_physical_cuts_are_empty_for_this_body():
    """This body has no physical mute or camera shutter (design record section 8)."""
    assert REACHY_MINI_PROFILE.physical_cuts == []


def test_speech_placement_is_pod_tier_for_v0_1():
    """The v0.1 baseline speech placement (design record decision 4)."""
    assert REACHY_MINI_PROFILE.speech_placement == "pod"
