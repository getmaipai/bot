"""VOICE-01: the sherpa engines, as far as they can be checked without the unit."""

from __future__ import annotations

import pytest

from maipai_body.speech import sherpa_engines


def test_a_missing_model_is_a_plain_error_that_says_what_to_do(tmp_path):
    # UNVERIFIED against real models (the unit and a loadable sherpa are absent).
    # This proves only that importing the module costs nothing and a missing file
    # is reported as the engine problem it is, with the next step.
    with pytest.raises(sherpa_engines.EngineUnavailable, match="fetch|sherpa"):
        sherpa_engines.SileroVad(tmp_path / "silero.onnx")
