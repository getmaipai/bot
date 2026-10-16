"""VOICE-01: the engine seams of the body's one speech process.

``SpeechProcess`` (``process.py``) owns the state machine and the ledger; the
models sit behind these four Protocols so the process is tested with scripted
engines and run with the ``sherpa-onnx`` ones in ``sherpa_engines.py``. All
audio here is 16 kHz mono float32 in [-1, 1], the shape ``AudioCapture``
already hands out.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt

Samples = npt.NDArray[np.float32]


class VadEngine(Protocol):
    """Silero voice activity, one 32 ms block at a time."""

    def is_speech(self, block: Samples) -> bool: ...

    def reset(self) -> None: ...


class SttEngine(Protocol):
    """Moonshine speech to text over one endpointed utterance.

    Returns ``""`` for nothing recognised; Moonshine tiny does that erratically
    behind a long silent head, which is what the process's retry from the onset
    block is for."""

    def transcribe(self, samples: Samples, sample_rate: int) -> str: ...


@dataclass(frozen=True)
class SpokenSegment:
    """One sentence of synthesis: the words and the audio that says them."""

    text: str
    samples: Samples
    sample_rate: int


class TtsEngine(Protocol):
    """A voice package's synthesis (Piper), one sentence segment at a time so
    playback can start before the reply is finished and the ledger can
    attribute audio to words."""

    @property
    def voice_id(self) -> str: ...

    def synthesize(self, text: str) -> Iterator[SpokenSegment]: ...


class SpeakerEmbedder(Protocol):
    """CAM++ over one utterance (SPEAK-01 consumes it)."""

    model_id: str
    model_sha256: str

    def embed(self, samples: Samples, sample_rate: int) -> Samples: ...


class StopDetector(Protocol):
    """VOICE-02 / BARGE-02: hears the stop word over the robot's own playback.

    Fed every captured block while the robot speaks; ``True`` once the word
    has been heard. ``reset`` runs when playback starts."""

    def accept(self, block: Samples) -> bool: ...

    def reset(self) -> None: ...
