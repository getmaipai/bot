"""VOICE-02: a stop word heard over the robot's own playback.

``TranscriptStopDetector`` is the first, engine-neutral detector: the VAD gates
a short span of captured speech, the speech-to-text engine transcribes it at
the end of the span, and the closed stop list decides. It runs on the array's
echo-cancelled channel; whether that channel really leaves the robot deaf to
its own voice is the bench row (M-R3, double-talk at real playback levels) and
is UNVERIFIED here. BARGE-02 swaps in the keyword spotter behind the same
``StopDetector`` seam so the word is caught mid-span, not at its end.
"""

from __future__ import annotations

import re

import numpy as np
import numpy.typing as npt

from maipai_body.speech.capture import BLOCK_DURATION_S
from maipai_body.speech.engines import SttEngine, VadEngine

# The stop command's phrases, plus the spoken ways to ask for quiet. Closed on purpose.
STOP_WORDS = frozenset({"stop", "quiet", "enough", "hush", "shush"})
MAX_WORDS = 4  # "stop talking", "okay stop that"; a long sentence containing "stop" is not a stop
SPAN_END_SILENCE_S = 0.3
MAX_SPAN_S = 2.5
SAMPLE_RATE = 16000


def is_stop_phrase(text: str) -> bool:
    words = re.sub(r"[^a-z' ]", " ", text.lower()).split()
    return 0 < len(words) <= MAX_WORDS and any(w in STOP_WORDS for w in words)


class TranscriptStopDetector:
    def __init__(self, vad: VadEngine, stt: SttEngine) -> None:
        self._vad = vad
        self._stt = stt
        self.reset()

    def reset(self) -> None:
        self._span: list[npt.NDArray[np.float32]] = []
        self._silence_s = 0.0
        self._vad.reset()

    def accept(self, block: npt.NDArray[np.float32]) -> bool:
        if self._vad.is_speech(block):
            self._span.append(block)
            self._silence_s = 0.0
        elif self._span:
            self._span.append(block)
            self._silence_s += BLOCK_DURATION_S
        else:
            return False
        if self._silence_s < SPAN_END_SILENCE_S and len(self._span) * BLOCK_DURATION_S < MAX_SPAN_S:
            return False
        span, self._span, self._silence_s = np.concatenate(self._span), [], 0.0
        try:
            return is_stop_phrase(self._stt.transcribe(span, SAMPLE_RATE) or "")
        except Exception:  # noqa: BLE001 - a failed check must not cut or crash the reply
            return False
