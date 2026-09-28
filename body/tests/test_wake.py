"""G2's own acceptance: the wake state machine, driven by a fake engine."""

from __future__ import annotations

import numpy as np
import pytest

from maipai_body.hal.seam import DirectionOfArrival
from maipai_body.speech.wake import WAKE_THRESHOLD, WakeEvent, WakeScorer


class _ScriptedEngine:
    """A `WakeEngine` that returns scores from a fixed script, one per
    `score()` call, and records every `reset()` call - the same
    scripted-fake shape this repo already uses for the daemon's own
    stand-ins (RM-03's fake sshd, G1's WAV-backed mic)."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = list(scores)
        self.reset_count = 0

    def score(self, block: np.ndarray) -> float:
        return self._scores.pop(0) if self._scores else 0.0

    def reset(self) -> None:
        self.reset_count += 1


class _StubAudio:
    """Only what `WakeScorer` needs from `AudioIO`: `get_doa()`."""

    def __init__(self, doa: DirectionOfArrival | None) -> None:
        self._doa = doa

    def get_doa(self) -> DirectionOfArrival | None:
        return self._doa


def _block() -> np.ndarray:
    return np.zeros(512, dtype=np.float32)


def test_a_block_below_threshold_produces_no_event():
    engine = _ScriptedEngine([0.1, 0.5, 0.79])
    scorer = WakeScorer(engine, _StubAudio(None))

    for _ in range(3):
        assert scorer.poll(_block()) is None
    assert scorer.last_score == pytest.approx(0.79)


def test_a_block_at_or_above_threshold_fires_exactly_once():
    engine = _ScriptedEngine([0.2, WAKE_THRESHOLD])
    scorer = WakeScorer(engine, _StubAudio(None))

    assert scorer.poll(_block()) is None
    event = scorer.poll(_block())

    assert isinstance(event, WakeEvent)
    assert event.score == pytest.approx(WAKE_THRESHOLD)


def test_firing_resets_the_engine_so_the_same_phrase_cannot_re_wake():
    """The empirically-confirmed bug this guards against: without a
    reset, the model's own rolling window still holds the phrase that
    just woke it and scores over threshold again on the very next
    block."""
    engine = _ScriptedEngine([0.95])
    scorer = WakeScorer(engine, _StubAudio(None))

    scorer.poll(_block())

    assert engine.reset_count == 1


def test_wake_captures_direction_of_arrival_at_the_wake_instant():
    doa = DirectionOfArrival(angle_rad=0.7, speech_detected=True)
    engine = _ScriptedEngine([0.9])
    scorer = WakeScorer(engine, _StubAudio(doa))

    event = scorer.poll(_block())

    assert event is not None
    assert event.doa == doa


def test_wake_with_no_doa_reading_reports_none_not_a_guess():
    engine = _ScriptedEngine([0.9])
    scorer = WakeScorer(engine, _StubAudio(None))

    event = scorer.poll(_block())

    assert event is not None
    assert event.doa is None


def test_a_custom_threshold_is_honored():
    engine = _ScriptedEngine([0.5])
    scorer = WakeScorer(engine, _StubAudio(None), threshold=0.4)

    event = scorer.poll(_block())

    assert event is not None
    assert event.score == pytest.approx(0.5)
