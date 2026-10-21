"""The per-turn microphone level line, the opt-in debug recording and the bounded capture queue."""

from __future__ import annotations

import wave

import av
import numpy as np

from maipai_body.bodies.stackchan.turn import (
    CAPTURE_QUEUE_BLOCKS,
    DEBUG_WAV_ENV,
    StackChanAudioCapture,
)


def _opus_packets(seconds: float, amplitude: float) -> list[bytes]:
    encoder = av.CodecContext.create("opus", "w")
    encoder.sample_rate = 16000
    encoder.layout = "mono"
    encoder.format = "s16"
    encoder.bit_rate = 24000
    encoder.options = {"application": "voip", "frame_duration": "60"}
    encoder.open()
    t = np.arange(int(16000 * seconds)) / 16000
    wave_ = (np.sin(2 * np.pi * 440 * t) * amplitude * 32767).astype(np.int16)
    packets: list[bytes] = []
    for start in range(0, len(wave_) - 959, 960):
        frame = av.AudioFrame.from_ndarray(
            wave_[start : start + 960].reshape(1, -1), format="s16", layout="mono"
        )
        frame.sample_rate = 16000
        packets.extend(bytes(p) for p in encoder.encode(frame))
    return packets


def test_peak_and_rms_describe_how_loud_the_microphone_was():
    quiet, loud = StackChanAudioCapture(), StackChanAudioCapture()
    for packet in _opus_packets(1.0, 0.05):
        quiet.feed_opus(packet)
    for packet in _opus_packets(1.0, 0.5):
        loud.feed_opus(packet)
    assert 0.02 < quiet.peak < 0.12 and 0.0 < quiet.rms < 0.08
    assert loud.peak > 0.3 and loud.rms > 5 * quiet.rms * 0.5


def test_the_capture_queue_is_bounded_and_drops_the_oldest_block():
    capture = StackChanAudioCapture()
    for index in range(CAPTURE_QUEUE_BLOCKS + 30):
        capture._queue_blocks(np.full(512, index / 1000.0, dtype=np.float32))
    assert capture._queue.qsize() == CAPTURE_QUEUE_BLOCKS
    assert capture._queue.get_nowait()[0] > 29 / 1000.0 - 1e-6  # the first 30 were dropped


def test_no_recording_is_kept_unless_the_folder_is_set(monkeypatch, tmp_path):
    monkeypatch.delenv(DEBUG_WAV_ENV, raising=False)
    capture = StackChanAudioCapture()
    for packet in _opus_packets(0.5, 0.3):
        capture.feed_opus(packet)
    assert capture.save_debug_wav(str(tmp_path), "x") is None
    assert list(tmp_path.iterdir()) == []


def test_the_opt_in_recording_is_a_16khz_mono_wav(monkeypatch, tmp_path):
    monkeypatch.setenv(DEBUG_WAV_ENV, str(tmp_path))
    capture = StackChanAudioCapture()
    for packet in _opus_packets(0.5, 0.3):
        capture.feed_opus(packet)
    path = capture.save_debug_wav(str(tmp_path), "turn")
    assert path is not None and path.exists()
    with wave.open(str(path), "rb") as played:
        assert played.getframerate() == 16000 and played.getnchannels() == 1
        assert played.getnframes() > 6000


def test_the_light_and_the_face_have_separate_workers():
    from types import SimpleNamespace

    from maipai_body.bodies.stackchan.turn import StackChanTurnBridge

    bridge = StackChanTurnBridge(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())
    try:
        assert bridge._side is not bridge._light_side
    finally:
        bridge.close()
