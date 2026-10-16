"""Scripted engines and a scripted capture for the speech-process tests."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import numpy.typing as npt

from maipai_body.speech.capture import BLOCK_SAMPLES
from maipai_body.speech.engines import SpokenSegment

SPEECH_LEVEL = 0.3
WAKE_LEVEL = 0.9


def silence(n: int = 1) -> list[npt.NDArray[np.float32]]:
    return [np.zeros(BLOCK_SAMPLES, np.float32) for _ in range(n)]


def speech(n: int = 1, level: float = SPEECH_LEVEL) -> list[npt.NDArray[np.float32]]:
    return [np.full(BLOCK_SAMPLES, level, np.float32) for _ in range(n)]


def wake_blocks(n: int = 1) -> list[npt.NDArray[np.float32]]:
    return speech(n, WAKE_LEVEL)


def seconds(s: float) -> int:
    return round(s / 0.032)


class ScriptedCapture:
    """``AudioCapture``'s ``poll_blocks`` over a prepared list.

    Without a clock it gives one block per call (the listening tests step it by
    hand). With a clock it releases blocks at real audio time, one per 32 ms, so
    a stop word arrives at the time it was said however fast the loop spins."""

    def __init__(self, blocks, clock=None) -> None:
        self._blocks = list(blocks)
        self._clock = clock
        self.polled = 0

    def poll_blocks(self):
        if self._clock is None:
            due = self.polled + 1
        else:
            due = int(self._clock() / 0.032 + 1e-9)
        out = []
        while self.polled < min(due, len(self._blocks)):
            out.append(self._blocks[self.polled])
            self.polled += 1
        if self._clock is None and not out:
            return silence(1)  # a live mic with nothing: silence
        return out

    @property
    def exhausted(self) -> bool:
        return self.polled >= len(self._blocks)


class LevelWakeEngine:
    def __init__(self) -> None:
        self.resets = 0

    def score(self, block) -> float:
        return 0.95 if abs(float(block[0]) - WAKE_LEVEL) < 1e-6 else 0.0

    def reset(self) -> None:
        self.resets += 1


class LevelVad:
    def is_speech(self, block) -> bool:
        return abs(float(block[0])) >= 0.1

    def reset(self) -> None:
        pass


class ScriptedStt:
    def __init__(self, *answers: str) -> None:
        self._answers = list(answers)
        self.calls: list[npt.NDArray[np.float32]] = []

    def transcribe(self, samples, sample_rate) -> str:
        self.calls.append(samples)
        return self._answers.pop(0) if self._answers else ""


class ScriptedTts:
    """Each sentence is 0.5 s of audio at 22.05 kHz (resampled by the process)."""

    voice_id = "voice-test"

    def __init__(self, rate: int = 22050, seconds_per_sentence: float = 0.5) -> None:
        self._rate = rate
        self._seconds = seconds_per_sentence
        self.texts: list[str] = []

    def synthesize(self, text: str) -> Iterator[SpokenSegment]:
        self.texts.append(text)
        for sentence in [s.strip() for s in text.replace("!", ".").split(".") if s.strip()]:
            n = round(self._rate * self._seconds)
            yield SpokenSegment(
                text=sentence + ".", samples=np.full(n, 0.1, np.float32), sample_rate=self._rate
            )


class HitAfter:
    """A stop detector that fires on its Nth accepted block."""

    def __init__(self, n: int) -> None:
        self._n = n
        self.seen = 0

    def accept(self, block) -> bool:
        self.seen += 1
        return self.seen >= self._n

    def reset(self) -> None:
        self.seen = 0
