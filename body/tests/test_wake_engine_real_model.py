"""G2's real-model acceptance: `OpenWakeWordEngine` against the actual
trained detector and front-end, not a fake.

Gated, not part of the always-on deterministic suite: the three model
files (melspectrogram, embedding, MaiPai's trained "hey maipai") are
real binary artifacts this repo never tracks (CLAUDE.md: "download,
don't vendor," "only artifacts we created may be tracked... even our
own large artifacts ship as release assets"). Point
``MAIPAI_WAKEWORD_MODELS_DIR`` at a local directory holding all three
(named exactly as `speech.models`'s own asset filenames) to run this;
otherwise every test here skips with a reason, never fails, matching
the live-daemon gate's own contract in conftest.py.
"""

from __future__ import annotations

import os
import wave
from pathlib import Path

import numpy as np
import pytest

from maipai_body.speech.wake import WAKE_THRESHOLD, OpenWakeWordEngine

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIPAI_WAKEWORD_MODELS_DIR"),
    reason="MAIPAI_WAKEWORD_MODELS_DIR is not set",
)


def _models_dir() -> Path:
    path = Path(os.environ["MAIPAI_WAKEWORD_MODELS_DIR"])
    required = ("melspectrogram.onnx", "embedding_model.onnx", "trained_hey_maipai_v2.onnx")
    missing = [name for name in required if not (path / name).exists()]
    if missing:
        pytest.skip(f"{path} is missing: {', '.join(missing)}")
    return path


def _engine() -> OpenWakeWordEngine:
    models = _models_dir()
    return OpenWakeWordEngine(
        wake_phrase_model=models / "trained_hey_maipai_v2.onnx",
        melspec_model=models / "melspectrogram.onnx",
        embedding_model=models / "embedding_model.onnx",
    )


def _load_16k_mono_float32(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != 16000 or handle.getnchannels() != 1:
            raise ValueError(f"{path} must be 16 kHz mono")
        raw = handle.readframes(handle.getnframes())
    return (np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0).astype(np.float32)


def _max_score_over(engine: OpenWakeWordEngine, samples: np.ndarray, block: int = 512) -> float:
    """Scores every complete block, including the last one: `range`'s own
    stop must be `len(samples) - block + 1`, not `- block`, or a sample
    count that's an exact multiple of `block` silently drops the final
    block - the one place a peak score is most likely to land."""
    engine.reset()
    peak = 0.0
    for i in range(0, len(samples) - block + 1, block):
        peak = max(peak, engine.score(samples[i : i + block]))
    return peak


def test_the_trained_phrase_wakes():
    """Requires a fixture named hey_maipai.wav (16 kHz mono) in
    MAIPAI_WAKEWORD_FIXTURES_DIR - skips cleanly if it isn't there,
    rather than synthesizing one on the fly (macOS `say` produced a
    reliable 0.94 during this feature's own development, but that's
    this dev Mac's own tool, not a portable test dependency). A real
    fixture proves the plumbing works; it's a synthetic-voice sanity
    check either way, not the real accuracy measurement (that's M-R3,
    on real human speech)."""
    engine = _engine()
    fixtures_dir = os.environ.get("MAIPAI_WAKEWORD_FIXTURES_DIR")
    if not fixtures_dir or not (Path(fixtures_dir) / "hey_maipai.wav").exists():
        pytest.skip("no hey_maipai.wav fixture in MAIPAI_WAKEWORD_FIXTURES_DIR")
    samples = _load_16k_mono_float32(Path(fixtures_dir) / "hey_maipai.wav")

    score = _max_score_over(engine, samples)

    assert score >= WAKE_THRESHOLD


def test_a_real_near_miss_is_rejected():
    """'hey my car' is a genuine, cleanly-rejected near miss on both real
    speech and this model (home issue #5's own bench table). 'hey my
    bike' is deliberately NOT tested here: it's a documented, permanent
    false-accept on real speech ('MaiPai' is phonetically 'my pie'),
    not a regression this suite should chase - see wake.py's own
    WAKE_THRESHOLD docstring."""
    engine = _engine()
    fixtures_dir = os.environ.get("MAIPAI_WAKEWORD_FIXTURES_DIR")
    if not fixtures_dir or not (Path(fixtures_dir) / "hey_my_car.wav").exists():
        pytest.skip("no hey_my_car.wav fixture in MAIPAI_WAKEWORD_FIXTURES_DIR")
    samples = _load_16k_mono_float32(Path(fixtures_dir) / "hey_my_car.wav")

    score = _max_score_over(engine, samples)

    assert score < WAKE_THRESHOLD


def test_reset_actually_clears_the_models_rolling_window():
    """The empirically-confirmed bug this session found: without reset(),
    silence fed right after a wake still scores over threshold because
    the phrase is still in the model's own rolling window."""
    engine = _engine()
    fixtures_dir = os.environ.get("MAIPAI_WAKEWORD_FIXTURES_DIR")
    if not fixtures_dir or not (Path(fixtures_dir) / "hey_maipai.wav").exists():
        pytest.skip("no hey_maipai.wav fixture available in this environment")
    samples = _load_16k_mono_float32(Path(fixtures_dir) / "hey_maipai.wav")
    silence = np.zeros(512, dtype=np.float32)

    engine.reset()
    for i in range(0, len(samples) - 512, 512):
        engine.score(samples[i : i + 512])
    score_without_reset = engine.score(silence)

    engine.reset()
    score_with_reset = engine.score(silence)

    assert score_without_reset >= WAKE_THRESHOLD
    assert score_with_reset < WAKE_THRESHOLD
