"""G1's own acceptance: a fake mic feeds fixed-size blocks with a real pre-roll."""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.speech.capture import BLOCK_SAMPLES, AudioCapture


def _write_tone_wav(path: Path, seconds: float, freq_hz: float = 440.0) -> None:
    """A synthetic mono 16 kHz tone - generated, never a committed binary
    fixture, so the exact sample count is known and reproducible."""
    sample_rate = 16000
    n = int(seconds * sample_rate)
    t = np.arange(n) / sample_rate
    tone = (0.2 * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)
    ints = (tone * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(ints.tobytes())


def test_a_3s_fixture_yields_about_94_blocks_of_512_mono_samples(tmp_path):
    wav_path = tmp_path / "tone-3s.wav"
    _write_tone_wav(wav_path, seconds=3.0)

    client = FakeReachyMiniClient(microphone_wav=wav_path)
    capture = AudioCapture(client)
    capture.start()

    # A single poll_blocks() call drains the whole fixture (it loops
    # get_audio_sample() internally until the fake returns None), so one
    # call is all a fully-drained read needs - see the next test for the
    # explicit assertion of that behavior.
    blocks = capture.poll_blocks()

    # 3 s at 16 kHz / 512 samples per block = 93.75 - 93 whole blocks, the
    # last partial one held as leftover rather than padded or dropped.
    assert len(blocks) == 93
    for block in blocks:
        assert block.shape == (BLOCK_SAMPLES,)
        assert block.dtype == np.float32


def test_a_single_poll_drains_every_buffer_queued_since_the_last_one(tmp_path):
    """A slow-polling caller must not fall behind the daemon's own queue:
    one poll_blocks() call keeps calling get_audio_sample() until it
    returns None, not just once."""
    wav_path = tmp_path / "tone-3s.wav"
    _write_tone_wav(wav_path, seconds=3.0)

    client = FakeReachyMiniClient(microphone_wav=wav_path)
    capture = AudioCapture(client)
    capture.start()

    blocks = capture.poll_blocks()

    assert len(blocks) == 93
    # Exhausted: a second poll gets nothing more, the same public signal a
    # real caller would see once the daemon's own queue runs dry.
    assert capture.poll_blocks() == []


def test_the_preroll_ring_holds_the_last_0_3_seconds(tmp_path):
    wav_path = tmp_path / "tone-1s.wav"
    _write_tone_wav(wav_path, seconds=1.0)

    client = FakeReachyMiniClient(microphone_wav=wav_path)
    capture = AudioCapture(client)
    capture.start()
    capture.poll_blocks()  # one call drains the whole fixture

    preroll = capture.preroll()
    # Rounds up, not to nearest: the ring must hold at least 0.3 s.
    expected_blocks = math.ceil((0.3 * 16000) / BLOCK_SAMPLES)
    assert len(preroll) == expected_blocks * BLOCK_SAMPLES


def test_poll_blocks_returns_nothing_before_start_or_under_one_block(tmp_path):
    wav_path = tmp_path / "tone-short.wav"
    _write_tone_wav(wav_path, seconds=0.01)  # well under one block

    client = FakeReachyMiniClient(microphone_wav=wav_path)
    capture = AudioCapture(client)

    # Not recording yet: the fake returns None, so no blocks at all.
    assert capture.poll_blocks() == []

    capture.start()
    assert capture.poll_blocks() == []  # under one block's worth queued


def test_start_is_idempotent_and_keeps_the_preroll_ring(tmp_path):
    """A second start() call mid-recording must not discard what
    poll_blocks() already captured into the pre-roll ring - it would, if
    start() called the client's start_recording() again unconditionally,
    since the fake resets its own cursor on every start_recording() call."""
    wav_path = tmp_path / "tone-1s.wav"
    _write_tone_wav(wav_path, seconds=1.0)

    client = FakeReachyMiniClient(microphone_wav=wav_path)
    capture = AudioCapture(client)
    capture.start()
    capture.poll_blocks()
    preroll_before = capture.preroll()
    assert len(preroll_before) > 0

    capture.start()  # idempotent: already recording, must be a no-op

    assert np.array_equal(capture.preroll(), preroll_before)


def test_start_raises_on_a_non_positive_sample_rate():
    """A vendor call returning 0 (or anything sizing to a non-positive
    block count) must fail loudly here, not divide by zero deep inside
    every subsequent poll_blocks() call."""

    class _ZeroRateClient(FakeReachyMiniClient):
        def get_input_audio_samplerate(self) -> int:  # type: ignore[override]
            return 0

    client = _ZeroRateClient()
    capture = AudioCapture(client)

    with pytest.raises(ValueError):
        capture.start()


def test_poll_blocks_raises_after_a_connection_loss_like_any_other_seam_call():
    client = FakeReachyMiniClient()
    capture = AudioCapture(client)
    capture.start()
    client.simulate_disconnect()

    with pytest.raises(Exception):
        capture.poll_blocks()
