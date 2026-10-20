"""The shared per-voice pitch offset (owner decision 2026-10-20)."""

from __future__ import annotations

import numpy as np
import pytest

from maipai_body.speech.pitch import clamp_semitones, shift_pitch

RATE = 24000


def _tone(hz: float, seconds: float = 1.0, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def _peak_hz(samples: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return float(np.argmax(spectrum) * RATE / len(samples))


def test_zero_semitones_returns_the_very_same_audio_untouched():
    samples = _tone(220.0)
    assert shift_pitch(samples, RATE, 0.0) is samples  # byte-identical: nothing processed
    assert shift_pitch(samples, RATE, 0) is samples


@pytest.mark.parametrize("semitones", [5.0, -1.0, 2.0, -7.0, 12.0])
def test_the_pitch_moves_by_the_offset_and_the_duration_is_kept(semitones):
    samples = _tone(200.0)
    shifted = shift_pitch(samples, RATE, semitones)
    expected = 200.0 * 2 ** (semitones / 12)
    assert abs(_peak_hz(shifted) - expected) / expected < 0.03
    assert abs(len(shifted) - len(samples)) <= 1440  # within one 60 ms frame
    assert float(np.max(np.abs(shifted))) <= 1.0


def test_loud_input_is_clipped_to_full_scale_not_beyond():
    shifted = shift_pitch(_tone(300.0, amplitude=0.99), RATE, 5.0)
    assert float(np.max(np.abs(shifted))) <= 1.0


def test_the_offset_is_clamped_to_plus_or_minus_twelve():
    assert clamp_semitones(30) == 12.0 and clamp_semitones(-30) == -12.0
    samples = _tone(150.0)
    octave_up = shift_pitch(samples, RATE, 40.0)
    assert abs(_peak_hz(octave_up) - 300.0) / 300.0 < 0.03


def test_a_very_short_sound_is_still_shifted_without_failing():
    short = _tone(400.0, seconds=0.03)
    out = shift_pitch(short, RATE, 5.0)
    assert len(out) > 0 and float(np.max(np.abs(out))) <= 1.0


def test_speech_like_input_keeps_its_loudness_roughly():
    rng = np.random.default_rng(1)
    carrier = _tone(180.0) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * np.arange(RATE) / RATE))
    samples = (carrier + 0.02 * rng.standard_normal(RATE)).astype(np.float32)
    shifted = shift_pitch(samples, RATE, -1.0)
    ratio = float(np.sqrt(np.mean(shifted**2)) / np.sqrt(np.mean(samples**2)))
    assert 0.7 < ratio < 1.3


def _playback_frames(pitch):
    """Push one second of tone through a real StackChanAudioPlayback and return the sent frames."""
    import asyncio
    import threading

    from maipai_body.bodies.stackchan.turn import StackChanAudioPlayback

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    sent: list[bytes] = []

    class _Server:
        _loop = loop

        async def send_audio(self, device_id, frames, **kwargs):
            sent.extend(frames)

        async def stop_audio(self, device_id):
            pass

    async def no_sleep(seconds):
        return None

    playback = StackChanAudioPlayback(
        _Server(), "device", async_sleep=no_sleep, pitch_semitones=lambda: pitch
    )
    samples = _tone(200.0)
    for index in range(0, len(samples), 2400):
        playback.push_audio_sample(samples[index : index + 2400])
    playback.stop_playing()
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    return sent


def test_pitch_zero_leaves_the_playback_audio_byte_identical():
    baseline = _playback_frames(0.0)
    assert baseline and baseline == _playback_frames(0.0)


def test_a_pitch_offset_changes_the_audio_but_keeps_the_reply_length():
    plain = _playback_frames(0.0)
    shifted = _playback_frames(-1.0)
    assert shifted != plain
    assert abs(len(shifted) - len(plain)) <= 2  # within a couple of 60 ms frames
