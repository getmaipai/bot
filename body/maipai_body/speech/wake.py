"""G2: wake-word detection over G1's capture blocks.

Scoped narrowly, unlike the legacy ``OnnxRecognizer`` this ports from
(`legacy-backups/bot-legacy.git:robot/robot/hal/drivers/voice.py`),
which combined wake, VAD, and STT into one state machine: the revised
streaming-turn design (`docs/dev/robot-streaming-turn-2026-09-28.md`)
moves VAD and STT to the hub's own streaming STT session, so this
module's whole job is "score audio, say when the phrase was heard,
forget what it heard once it fires."
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel

from maipai_body.hal.seam import AudioIO, DirectionOfArrival

# The trained detector's own threshold, from MaiPai Home's wake-word
# manifest (legacy-backups/home-legacy.git:backend/assets/wakewords/
# trained-manifest.json). Tracks the MODEL, not a taste setting: v2 is
# calibrated for 0.8. Measured on real speech: 0.00 false accepts/hr at
# 85% recall (home issue #5's own bench table: 0.956-0.975 on "hey
# maipai," cleanly rejects "hey my car"). Known, permanent, and not a
# regression to chase: it also fires on "hey my bike" on real speech -
# "MaiPai" is phonetically "my pie," and no retraining separates sounds
# that are not different (home issue #5, closed as won't-fix).
WAKE_THRESHOLD = 0.8


class WakeEngine(Protocol):
    """The scoring backend `WakeScorer` drives - a real ONNX model in
    production, a scripted fake in tests. Ported from the same-named
    Protocol in the legacy voice.py this module replaces."""

    def score(self, block: npt.NDArray[np.float32]) -> float: ...

    def reset(self) -> None:
        """Forget the audio scored so far. Required after every wake:
        without it the phrase that just woke the robot is still in the
        model's own rolling window and scores over threshold again on
        the very next block - empirically confirmed against the real
        model (silence immediately after a wake still scored 0.94
        without a reset, 0.0 with one)."""


class WakeEvent(BaseModel):
    """Emitted once per wake, never more than once per phrase - the
    caller resets the scorer before the next word can fire again."""

    score: float
    doa: DirectionOfArrival | None = None


class WakeScorer:
    """Feeds `AudioCapture` blocks to a `WakeEngine`, watches for the
    threshold crossing, and captures direction of arrival at the wake
    instant (the array's beams haven't had time to move yet, unlike a
    later read at speech onset, which G3's own state machine owns)."""

    def __init__(
        self,
        engine: WakeEngine,
        audio: AudioIO,
        *,
        threshold: float = WAKE_THRESHOLD,
    ) -> None:
        self._engine = engine
        self._audio = audio
        self._threshold = threshold
        self.last_score = 0.0

    def poll(self, block: npt.NDArray[np.float32]) -> WakeEvent | None:
        """Score one block. Returns a `WakeEvent` the instant the score
        crosses threshold, and resets the engine before returning so a
        caller that keeps polling never sees a second immediate wake
        from the same phrase still sitting in the model's own buffer."""
        self.last_score = self._engine.score(block)
        if self.last_score < self._threshold:
            return None
        event = WakeEvent(score=self.last_score, doa=self._audio.get_doa())
        self._engine.reset()
        return event


class OpenWakeWordEngine:
    """The real `WakeEngine`: openWakeWord's own `Model`, pointed at
    local files. openWakeWord downloads its shared front-end on first
    use by default; passing all three paths explicitly (mirroring the
    legacy driver this replaces) is what keeps model loading itself
    offline - fetching them is `models.ensure_wakeword_models`'s job,
    called once before this is constructed, never lazily inside it."""

    def __init__(
        self,
        *,
        wake_phrase_model: Path,
        melspec_model: Path,
        embedding_model: Path,
    ) -> None:
        from openwakeword.model import Model  # heavy import, only when used

        self._model = Model(
            wakeword_models=[str(wake_phrase_model)],
            melspec_model_path=str(melspec_model),
            embedding_model_path=str(embedding_model),
            inference_framework="onnx",
        )

    def score(self, block: npt.NDArray[np.float32]) -> float:
        # openWakeWord's own contract is int16 PCM, not the seam's
        # float32; this is the one place that conversion happens.
        samples = np.clip(block * 32768.0, -32768, 32767).astype(np.int16)
        scores = self._model.predict(samples)
        return max(scores.values()) if scores else 0.0

    def reset(self) -> None:
        self._model.reset()
