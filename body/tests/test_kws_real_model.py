"""Rung 1's real-model acceptance: the sherpa-onnx spotter against fixtures.

Gated like the wake model's: point ``MAIPAI_KWS_MODELS_DIR`` at a directory
holding the four model files named in ``speech.kws.MODEL_FILES`` (what
``ensure_kws_model`` unpacks; ``bpe.model`` beside them also runs the keyword
file check) and ``uv sync --extra kws``; otherwise every test skips.

The fixtures are SYNTHESIZED speech (`tests/fixtures/kws/README.md`), two
Piper voices. They prove the plumbing and the closed list; they are not the
accuracy measurement, which is real microphone audio on the unit
(`scripts/measure_kws.py`, UNVERIFIED).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("sherpa_onnx", reason="the kws extra is not installed")

from maipai_body.link.commands import COMMAND_PHRASES, LocalCommand, route_phrase  # noqa: E402
from maipai_body.measure.kws import (  # noqa: E402
    ClipResult,
    listen_to_clip,
    load_wav_16k_mono,
    summarize_accuracy,
)
from maipai_body.speech import kws  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIPAI_KWS_MODELS_DIR"), reason="MAIPAI_KWS_MODELS_DIR is not set"
)

FIXTURES = Path(__file__).parent / "fixtures" / "kws"


def _model_dir() -> Path:
    path = Path(os.environ["MAIPAI_KWS_MODELS_DIR"])
    missing = [n for n in kws.MODEL_FILES.values() if not (path / n).exists()]
    if missing:
        pytest.skip(f"{path} is missing: {', '.join(missing)}")
    return path


@pytest.fixture(scope="module")
def recognizer():
    return kws.KeywordSpotterRecognizer(kws.SherpaKeywordEngine(_model_dir()))


@pytest.fixture(scope="module")
def results(recognizer):
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    out = []
    for entry in manifest["fixtures"]:
        expected = None
        if entry["kind"] == "command":
            expected = COMMAND_PHRASES[LocalCommand(entry["command"])][0]
        heard = listen_to_clip(recognizer, load_wav_16k_mono(FIXTURES / entry["file"]))
        out.append((entry, ClipResult(entry["file"], expected, heard)))
    return out


def test_each_command_is_heard_in_at_least_one_fixture(results):
    heard = {
        route_phrase(r.heard)
        for entry, r in results
        if entry["kind"] == "command" and r.heard is not None
    }
    assert heard == set(LocalCommand)


def test_no_fixture_is_heard_as_the_wrong_command(results):
    wrong = [
        r
        for entry, r in results
        if entry["kind"] == "command" and r.heard not in (None, r.expected)
    ]
    assert wrong == []


def test_the_near_miss_list_yields_nothing(results):
    heard = [(r.name, r.heard) for entry, r in results if entry["kind"] == "near_miss" and r.heard]
    assert heard == []


def test_the_recorded_counts(results):
    acc = summarize_accuracy([r for _entry, r in results])
    # Observed, not promised: a miss is a command not heard, which the funnel
    # drops. Any change here is a change to the pinned model, the keyword file
    # or the operating point, and wants a new measurements row.
    assert (acc.commands, acc.recalled, acc.wrong_command) == (22, 17, 0)
    assert (acc.near_misses, acc.false_accepts) == (48, 0)


def test_silence_yields_nothing(recognizer):
    import numpy as np

    assert listen_to_clip(recognizer, np.zeros(16000, np.float32)) is None


def test_a_command_inside_longer_speech_is_still_a_command_not_a_transcript(recognizer):
    # Keyword spotting is substring-like and the window bounds it: the heard value is
    # always a phrase of the closed list, never free text.
    heard = listen_to_clip(recognizer, load_wav_16k_mono(FIXTURES / "amy-low__stop_it.wav"))
    assert heard in (None, "stop")


def test_the_committed_keywords_file_matches_the_pinned_models_bpe():
    bpe = _model_dir() / "bpe.model"
    if not bpe.exists():
        pytest.skip("bpe.model is not beside the model files")
    pytest.importorskip("sentencepiece")
    assert kws.render_keywords(bpe) == kws.keywords_text()
