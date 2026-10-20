"""BOT-SC-DANCE-01 (host half): a pure-numpy music detector.

Scores a rolling 4.0 s window of mono float32 audio (16 kHz, as
``speech/capture.py``'s ``poll_blocks`` yields it) between 0.0 and 1.0.
The score blends two cues: beat periodicity (autocorrelation of the
per-frame energy envelope over the 60 to 180 BPM lag range) and
tonality (per-frame 1 - spectral flatness of the magnitude spectrum),
with a loudness gate that zeroes out near-silence. Speech is bursty
with low beat regularity, and noise has high spectral flatness, so
both cues push away from the two things this must not fire on.

Every number in this module is an UNMEASURED design default: the window
length, the frame size, the BPM range, the loudness gate and the
0.6/0.4 weights have not been tuned against real recordings. The
method is deliberately simple, so a future measurement pass can
re-weight or replace a cue without touching the caller. Nothing is
written to disk; the only state is the in-memory rolling window.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np
import numpy.typing as npt

WINDOW_S = 4.0
MIN_WINDOW_S = 3.0
FRAME_S = 0.032
MIN_RMS = 0.01
MIN_BPM = 60.0
MAX_BPM = 3.0 * MIN_BPM  # 60 to 180 BPM
WEIGHT_BEAT = 0.6
WEIGHT_TONALITY = 0.4
# relative to a frame's own peak magnitude: keeps the geometric mean of a
# floor-clipped magnitude spectrum finite on the quiet bins
FLATNESS_FLOOR = 1e-9
# frames quieter than this (sum of squares over the frame) are excluded
# from the tonality average: a silent frame's flatness is meaningless
ACTIVE_FRAME_ENERGY = 1e-6


class MusicDetector:
    """Feeds blocks of mono audio, reports a 0..1 music score.

    Call :meth:`accept` with blocks of any length (a 32 ms capture block
    per tick is the expected cadence), then read :meth:`music_score` or
    :meth:`is_music`. The window holds at most the last 4.0 s of audio;
    older samples are dropped on every :meth:`accept`.
    """

    def __init__(self, *, sample_rate: int = 16000) -> None:
        self._sample_rate = sample_rate
        self._frame_samples = round(FRAME_S * sample_rate)
        self._max_samples = round(WINDOW_S * sample_rate)
        self._min_samples = round(MIN_WINDOW_S * sample_rate)
        self._chunks: deque[npt.NDArray[np.float32]] = deque()
        self._window_len = 0

    def accept(self, block: npt.NDArray[np.float32]) -> None:
        """Add one block of audio; the window never holds more than 4.0 s."""
        arr = np.asarray(block, dtype=np.float32).ravel()
        if arr.size == 0:
            return
        self._chunks.append(arr)
        self._window_len += arr.size
        while self._window_len > self._max_samples:
            if len(self._chunks) == 1:
                # one chunk longer than the whole window: keep its tail
                self._chunks.clear()
                self._chunks.append(arr[-self._max_samples :])
                self._window_len = self._max_samples
                return
            self._window_len -= self._chunks.popleft().size

    def music_score(self) -> float:
        """The current 0..1 music score; 0.0 until the window holds 3.0 s."""
        if self._window_len < self._min_samples:
            return 0.0
        window = np.concatenate(list(self._chunks)).astype(np.float64)
        rms = math.sqrt(float(np.mean(window * window)))
        if rms < MIN_RMS:
            return 0.0
        n_frames = len(window) // self._frame_samples
        if n_frames < 2:
            return 0.0
        frames = window[: n_frames * self._frame_samples].reshape(n_frames, self._frame_samples)
        energy = np.mean(frames * frames, axis=1)
        beat = self._beat_score(energy)
        tonality = self._tonality(frames)
        score = WEIGHT_BEAT * beat + WEIGHT_TONALITY * tonality
        return float(min(1.0, max(0.0, score)))

    def is_music(self, threshold: float = 0.55) -> bool:
        """Whether the current score clears ``threshold`` (UNMEASURED)."""
        return self.music_score() >= threshold

    def _beat_score(self, energy: npt.NDArray[np.float64]) -> float:
        """Peak normalized autocorrelation of the mean-removed envelope
        over the 60..180 BPM lag range, clipped to 0..1."""
        x = energy - energy.mean()
        r0 = float(np.dot(x, x))
        if r0 <= 0.0:
            return 0.0
        min_lag = max(1, math.ceil((60.0 / MAX_BPM) / FRAME_S))
        max_lag = min(len(x) - 1, math.floor((60.0 / MIN_BPM) / FRAME_S))
        if max_lag <= min_lag:
            return 0.0
        corr = np.correlate(x, x, mode="full")
        peak = float(corr[len(x) - 1 + min_lag : len(x) - 1 + max_lag + 1].max())
        return float(min(1.0, max(0.0, peak / r0)))

    def _tonality(self, frames: npt.NDArray[np.float64]) -> float:
        """Mean over active frames of 1 - spectral flatness, clipped 0..1."""
        active = np.sum(frames * frames, axis=1) > ACTIVE_FRAME_ENERGY
        if not np.any(active):
            return 0.0
        scores: list[float] = []
        for frame in frames[active]:
            magnitude = np.abs(np.fft.rfft(frame))
            peak = float(magnitude.max())
            if peak <= 0.0:
                continue
            floored = np.maximum(magnitude, peak * FLATNESS_FLOOR)
            log_mean = float(np.mean(np.log(floored)))
            flatness = math.exp(log_mean) / float(np.mean(magnitude))
            scores.append(min(1.0, max(0.0, 1.0 - flatness)))
        if not scores:
            return 0.0
        return float(np.mean(scores))
