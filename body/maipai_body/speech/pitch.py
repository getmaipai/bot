"""A plain per-voice pitch offset (owner decision 2026-10-20): ``shift_pitch``.

A voice record may carry ``pitch_semitones`` (-12 to 12). The robot and Home apply it with this one
method so both sound the same: WSOLA time-stretch by r = 2 ** (semitones / 12), then a polyphase
resample by 1 / r. Pitch moves by the offset and the duration is kept (within one frame). The
formants move with the pitch (no formant preservation). At 0 semitones the input array itself is
returned, so the audio is byte-identical and nothing is processed.

Parameters (the contract Home should match): analysis window 40 ms with a Hann window, synthesis
hop 20 ms, a search of +/- 5 ms for the best cross-correlation against the natural continuation
of the previous segment, output clipped to [-1, 1].
"""

from __future__ import annotations

from fractions import Fraction

import numpy as np
import numpy.typing as npt

MAX_SEMITONES = 12.0
WINDOW_S = 0.040
HOP_S = 0.020
SEARCH_S = 0.005


def clamp_semitones(semitones: float) -> float:
    return max(-MAX_SEMITONES, min(MAX_SEMITONES, float(semitones)))


def shift_pitch(
    samples: npt.NDArray[np.float32], sample_rate: int, semitones: float
) -> npt.NDArray[np.float32]:
    """Return ``samples`` raised by ``semitones``; the same array when the offset is 0."""
    semitones = clamp_semitones(semitones)
    if semitones == 0.0 or len(samples) == 0:
        return samples
    ratio = 2.0 ** (semitones / 12.0)
    window = int(WINDOW_S * sample_rate)
    if len(samples) < 2 * window:
        stretched = np.asarray(samples, dtype=np.float32)  # too short to stretch: resample only
    else:
        stretched = _wsola_stretch(np.asarray(samples, dtype=np.float32), sample_rate, ratio)
    shifted = _resample(stretched, 1.0 / ratio)
    shifted = _fit_length(shifted, len(samples) if len(samples) >= 2 * window else None)
    return np.clip(shifted, -1.0, 1.0).astype(np.float32)


def _wsola_stretch(x: np.ndarray, sample_rate: int, ratio: float) -> np.ndarray:
    """Time-stretch by ``ratio`` (longer when above 1) without changing the pitch."""
    window = int(WINDOW_S * sample_rate)
    hop = int(HOP_S * sample_rate)
    tol = int(SEARCH_S * sample_rate)
    taper = np.hanning(window).astype(np.float32)
    out_len = int(len(x) * ratio) + window
    out = np.zeros(out_len, dtype=np.float32)
    weight = np.zeros(out_len, dtype=np.float32)
    padded = np.concatenate((x, np.zeros(window + 2 * tol + hop, dtype=np.float32)))
    previous = 0
    frame = 0
    position = 0
    while position + window <= out_len:
        ideal = int(round(frame * hop / ratio))
        if ideal >= len(x):
            break
        if frame == 0:
            start = ideal
        else:
            target = padded[previous + hop : previous + hop + window]
            low = max(0, ideal - tol)
            high = min(len(x), ideal + tol)
            if high <= low:
                start = ideal
            else:
                candidates = np.lib.stride_tricks.sliding_window_view(
                    padded[low : high + window], window
                )[: high - low]
                start = low + int(np.argmax(candidates @ target))
        segment = padded[start : start + window] * taper
        out[position : position + window] += segment
        weight[position : position + window] += taper
        previous = start
        position += hop
        frame += 1
    out /= np.maximum(weight, 1e-6)
    return out[: int(len(x) * ratio)]


def _resample(x: np.ndarray, factor: float) -> np.ndarray:
    """Resample so the output has ``factor`` times as many samples."""
    fraction = Fraction(factor).limit_denominator(1000)
    try:
        from scipy.signal import resample_poly

        return resample_poly(x, fraction.numerator, fraction.denominator).astype(np.float32)
    except ImportError:
        target = max(1, int(round(len(x) * factor)))
        return np.interp(np.linspace(0, len(x) - 1, target), np.arange(len(x)), x).astype(
            np.float32
        )


def _fit_length(x: np.ndarray, length: int | None) -> np.ndarray:
    if length is None:
        return x
    if len(x) >= length:
        return x[:length]
    return np.pad(x, (0, length - len(x)))
