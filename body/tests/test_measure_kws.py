"""Rung 1 keyword spotter measurement helpers: scoring and the CPU probe."""

from __future__ import annotations

import wave

import numpy as np
import pytest

from maipai_body.measure.kws import (
    ClipCapture,
    ClipResult,
    listen_to_clip,
    load_wav_16k_mono,
    probe_cpu,
    summarize_accuracy,
)
from maipai_body.speech.capture import BLOCK_SAMPLES
from maipai_body.speech.kws import KeywordSpotterRecognizer


class _Engine:
    def __init__(self, tag=None, fire_at=None):
        self.tag, self.fire_at, self.n = tag, fire_at, 0
        self.fed = 0

    def begin(self):
        self.n = 0

    def accept(self, block):
        self.n += 1
        self.fed += 1
        return self.tag if self.n == self.fire_at else None

    def finish(self):
        return None


def test_accuracy_counts_recall_wrong_commands_and_false_accepts():
    results = [
        ClipResult("a", "stop", "stop"),
        ClipResult("b", "stop", None),
        ClipResult("c", "louder", "quieter"),
        ClipResult("d", None, None),
        ClipResult("e", None, "stop"),
    ]
    acc = summarize_accuracy(results)
    assert (acc.commands, acc.recalled, acc.wrong_command) == (3, 1, 1)
    assert (acc.near_misses, acc.false_accepts) == (2, 1)
    assert acc.recall == pytest.approx(1 / 3)
    assert acc.false_accept_rate == pytest.approx(0.5)


def test_a_clip_is_handed_out_in_whole_blocks_then_nothing():
    capture = ClipCapture(np.zeros(BLOCK_SAMPLES * 2 + 100, np.float32))
    assert len(capture.poll_blocks()) == 1
    assert len(capture.poll_blocks()) == 1
    assert capture.poll_blocks() == []


def test_a_short_clip_is_padded_to_the_window_so_the_listen_ends_on_audio_not_the_wall_clock():
    engine = _Engine()
    recognizer = KeywordSpotterRecognizer(engine, window_s=1.0)
    assert listen_to_clip(recognizer, np.zeros(1600, np.float32)) is None
    assert engine.fed == 32  # the whole window, 1.0 s of 32 ms blocks, rounded up


def test_a_hit_in_a_clip_is_returned():
    recognizer = KeywordSpotterRecognizer(_Engine("stop", fire_at=4), window_s=1.0)
    assert listen_to_clip(recognizer, np.zeros(16000, np.float32)) == "stop"


def test_the_cpu_probe_reports_cpu_seconds_per_audio_second():
    cpu = iter(range(1000))
    engine = _Engine()
    probe = probe_cpu(
        engine,
        np.zeros(BLOCK_SAMPLES * 4, np.float32),
        seconds=2.048,  # 64 blocks, looped over the 4 in the clip
        pace=False,
        process_time=lambda: float(next(cpu)) * 0.5,
    )
    assert engine.fed == 64
    assert probe.audio_s == pytest.approx(2.048)
    assert probe.cpu_s == pytest.approx(0.5)
    assert probe.real_time_factor == pytest.approx(0.5 / 2.048)


def test_a_paced_probe_sleeps_to_real_time():
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    probe_cpu(
        _Engine(),
        np.zeros(BLOCK_SAMPLES, np.float32),
        seconds=0.32,
        pace=True,
        process_time=lambda: 0.0,
        monotonic=lambda: now[0],
        sleep=sleep,
    )
    assert sum(slept) == pytest.approx(0.32)


def test_a_clip_shorter_than_a_block_is_refused():
    with pytest.raises(ValueError):
        probe_cpu(_Engine(), np.zeros(10, np.float32), seconds=1.0, pace=False)


def test_a_wav_must_be_16k_mono(tmp_path):
    path = tmp_path / "x.wav"
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(44100)
        f.writeframes(b"\0\0" * 100)
    with pytest.raises(ValueError):
        load_wav_16k_mono(path)
