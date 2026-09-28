"""G1's own acceptance: pushed audio reaches the client and is ledgered."""

from __future__ import annotations

import numpy as np
import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.speech.playback import AudioPlayback


def test_push_opens_the_stream_once_and_forwards_every_chunk():
    client = FakeReachyMiniClient()
    playback = AudioPlayback(client)

    chunk_a = np.ones(160, dtype=np.float32)
    chunk_b = np.zeros(160, dtype=np.float32)
    playback.push(chunk_a)
    playback.push(chunk_b)

    assert len(client.pushed_audio) == 2
    assert np.array_equal(client.pushed_audio[0], chunk_a)
    assert np.array_equal(client.pushed_audio[1], chunk_b)
    assert client._playing is True


def test_push_is_idempotent_about_opening_the_stream():
    """start_playing() reaches the client exactly once across several pushes."""

    class _CountingClient(FakeReachyMiniClient):
        def __init__(self) -> None:
            super().__init__()
            self.start_playing_calls = 0

        def start_playing(self) -> None:  # type: ignore[override]
            super().start_playing()
            self.start_playing_calls += 1

    client = _CountingClient()
    playback = AudioPlayback(client)

    for _ in range(3):
        playback.push(np.zeros(10, dtype=np.float32))

    assert client.start_playing_calls == 1


def test_the_ledger_reports_the_total_pushed_duration():
    client = FakeReachyMiniClient()  # 16 kHz, per get_output_audio_samplerate
    playback = AudioPlayback(client)

    playback.push(np.zeros(1600, dtype=np.float32))  # 0.1 s
    playback.push(np.zeros(3200, dtype=np.float32))  # 0.2 s

    assert playback.pushed_duration_s() == pytest.approx(0.3)


def test_stop_closes_the_stream_but_keeps_the_ledger_readable():
    """Barge-in's natural order: stop(), then ask how much was heard."""
    client = FakeReachyMiniClient()
    playback = AudioPlayback(client)
    playback.push(np.zeros(1600, dtype=np.float32))  # 0.1 s

    playback.stop()

    assert client._playing is False
    assert playback.pushed_duration_s() == pytest.approx(0.1)


def test_the_next_replys_start_clears_the_previous_ledger():
    client = FakeReachyMiniClient()
    playback = AudioPlayback(client)
    playback.push(np.zeros(1600, dtype=np.float32))
    playback.stop()

    playback.push(np.zeros(3200, dtype=np.float32))  # 0.2 s, a new reply

    assert playback.pushed_duration_s() == pytest.approx(0.2)


def test_push_raises_after_a_connection_loss_like_any_other_seam_call():
    client = FakeReachyMiniClient()
    playback = AudioPlayback(client)
    client.simulate_disconnect()

    with pytest.raises(Exception):
        playback.push(np.zeros(10, dtype=np.float32))
