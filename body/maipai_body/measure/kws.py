"""Rung 1 keyword spotter measurement: accuracy over wavs, and a CPU probe.

Counts only, never audio or transcripts. ``score_clips`` runs each clip
through a fresh listen, so the same code scores the synthesized test
fixtures and real-microphone recordings alike.
"""

from __future__ import annotations

import threading
import time
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from maipai_body.speech.capture import BLOCK_SAMPLES
from maipai_body.speech.kws import SAMPLE_RATE, KeywordSpotterRecognizer


def load_wav_16k_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as f:
        if f.getframerate() != SAMPLE_RATE or f.getnchannels() != 1 or f.getsampwidth() != 2:
            raise ValueError(f"{path} must be 16 kHz mono 16-bit")
        raw = f.readframes(f.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


class ClipCapture:
    """An ``AudioCapture`` stand-in that hands one clip out in 32 ms blocks."""

    def __init__(self, samples: np.ndarray) -> None:
        self._blocks = [
            samples[i : i + BLOCK_SAMPLES]
            for i in range(0, len(samples) - BLOCK_SAMPLES + 1, BLOCK_SAMPLES)
        ]
        self._next = 0

    def poll_blocks(self):
        if self._next >= len(self._blocks):
            return []
        block = self._blocks[self._next]
        self._next += 1
        return [block]


def listen_to_clip(recognizer: KeywordSpotterRecognizer, samples: np.ndarray) -> str | None:
    # Silence after the clip, as a live stream has until the window ends; a clip
    # longer than the window is cut at the window, as it would be live.
    short = max(0, int((recognizer.window_s + 0.5) * SAMPLE_RATE) - len(samples))
    padded = np.concatenate([samples, np.zeros(short, np.float32)])
    return recognizer.listen(ClipCapture(padded), threading.Event())


@dataclass(frozen=True)
class FalseAccepts:
    windows: int
    accepted: int
    wake_events_per_hour: float

    @property
    def per_window(self) -> float:
        return self.accepted / self.windows if self.windows else float("nan")

    @property
    def projected_per_hour(self) -> float:
        return self.per_window * self.wake_events_per_hour


def score_false_accept_windows(
    engine,
    samples: np.ndarray,
    *,
    wake_events_per_hour: float,
    window_s: float = 4.0,
) -> FalseAccepts:
    """Score independent non-command windows matching the recognizer's post-wake listen."""
    if window_s <= 0:
        raise ValueError("window_s must be positive")
    if wake_events_per_hour < 0:
        raise ValueError("wake_events_per_hour must be non-negative")
    window_samples = int(window_s * SAMPLE_RATE)
    count = len(samples) // window_samples
    accepted = 0
    bounded = KeywordSpotterRecognizer(engine, window_s=window_s)
    for i in range(count):
        window = samples[i * window_samples : (i + 1) * window_samples]
        accepted += listen_to_clip(bounded, window) is not None
    return FalseAccepts(count, accepted, wake_events_per_hour)


@dataclass(frozen=True)
class ClipResult:
    name: str
    expected: str | None  # the phrase that should be heard, None for a near miss
    heard: str | None


@dataclass(frozen=True)
class Accuracy:
    commands: int
    recalled: int
    wrong_command: int
    near_misses: int
    false_accepts: int

    @property
    def recall(self) -> float:
        return self.recalled / self.commands if self.commands else float("nan")

    @property
    def false_accept_rate(self) -> float:
        return self.false_accepts / self.near_misses if self.near_misses else float("nan")


def summarize_accuracy(results: Sequence[ClipResult]) -> Accuracy:
    commands = [r for r in results if r.expected is not None]
    near = [r for r in results if r.expected is None]
    return Accuracy(
        commands=len(commands),
        recalled=sum(r.heard == r.expected for r in commands),
        wrong_command=sum(r.heard is not None and r.heard != r.expected for r in commands),
        near_misses=len(near),
        false_accepts=sum(r.heard is not None for r in near),
    )


@dataclass(frozen=True)
class CpuProbe:
    audio_s: float
    cpu_s: float

    @property
    def real_time_factor(self) -> float:
        """CPU seconds per second of audio, on one core; 1.0 would be a full core."""
        return self.cpu_s / self.audio_s


def probe_cpu(
    engine,
    samples: np.ndarray,
    *,
    seconds: float,
    pace: bool,
    process_time: Callable[[], float] = time.process_time,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> CpuProbe:
    """Feed ``samples`` to ``engine`` in 32 ms blocks, looping, for ``seconds`` of
    audio. With ``pace`` the blocks arrive at real-time speed (what a live
    microphone does and what M-R1's sampler should see); without, as fast as the
    spotter runs (its ceiling)."""
    blocks = [
        samples[i : i + BLOCK_SAMPLES]
        for i in range(0, len(samples) - BLOCK_SAMPLES + 1, BLOCK_SAMPLES)
    ]
    if not blocks:
        raise ValueError("the clip is shorter than one block")
    total = int(seconds * SAMPLE_RATE / BLOCK_SAMPLES)
    engine.begin()
    cpu0, t0 = process_time(), monotonic()
    for i in range(total):
        engine.accept(blocks[i % len(blocks)])
        if pace:
            wait = t0 + (i + 1) * BLOCK_SAMPLES / SAMPLE_RATE - monotonic()
            if wait > 0:
                sleep(wait)
    return CpuProbe(audio_s=total * BLOCK_SAMPLES / SAMPLE_RATE, cpu_s=process_time() - cpu0)
