"""VOICE-03: the robot's speech normalizer is the spec's, loaded from the pin.

The hub and the robot must say the same words for the same reply text, so the
robot never carries a second implementation: it loads
``voice/py/normalize_for_speech.py`` from the pinned ``@maipai/spec`` source
(the same ``MAIPAI_SPEC_DIR`` / ``spec_pin`` lookup the asset pins use) and the
fixture file ``voice/fixtures/normalize-for-speech.json`` is the proof both
sides pass. The spec module needs ``num2words`` (the ``voice`` extra).
"""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Callable
from pathlib import Path

from maipai_body.spec_pin import SPEC_CHECKOUT

_MODULE_NAME = "maipai_spec_normalize_for_speech"


class NormalizerUnavailable(RuntimeError):
    """The pinned normalizer cannot be loaded; the message says what to do."""


def spec_dir() -> Path:
    override = os.environ.get("MAIPAI_SPEC_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3].parent / SPEC_CHECKOUT


def fixtures_path(root: Path | None = None) -> Path:
    return (root or spec_dir()) / "voice" / "fixtures" / "normalize-for-speech.json"


def load_normalizer(root: Path | None = None) -> Callable[[str], str]:
    source = (root or spec_dir()) / "voice" / "py" / "normalize_for_speech.py"
    if not source.is_file():
        raise NormalizerUnavailable(
            f"the pinned speech normalizer is missing at {source}; "
            "set MAIPAI_SPEC_DIR to the pinned spec/ directory"
        )
    module_spec = importlib.util.spec_from_file_location(_MODULE_NAME, source)
    if module_spec is None or module_spec.loader is None:
        raise NormalizerUnavailable(f"the speech normalizer at {source} cannot be imported")
    module = importlib.util.module_from_spec(module_spec)
    try:
        module_spec.loader.exec_module(module)
    except ModuleNotFoundError as exc:
        raise NormalizerUnavailable(
            f"the speech normalizer needs {exc.name}; run `uv sync --extra voice`"
        ) from exc
    return module.normalize_for_speech


def load_fixtures(root: Path | None = None) -> list[dict[str, str]]:
    return json.loads(fixtures_path(root).read_text(encoding="utf-8"))
