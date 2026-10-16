"""BARGE-02: the playback side. Flush, generation tags, the reply tail, the stop spotter."""

from __future__ import annotations

import numpy as np

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient, ManualClock
from maipai_body.speech.barge import BLEED_GRACE_S, talk_over
from maipai_body.speech.kws import KeywordStopDetector
from maipai_body.speech.playback import TAIL_S, AudioPlayback


def chunk(seconds: float) -> np.ndarray:
    return np.full(int(16000 * seconds), 0.1, np.float32)


def build() -> tuple[AudioPlayback, FakeReachyMiniClient, ManualClock]:
    clock = ManualClock()
    client = FakeReachyMiniClient(clock=clock)
    return AudioPlayback(client, clock=clock), client, clock


def test_flush_drops_the_daemon_queue_and_nothing_plays_after_it() -> None:
    playback, client, _ = build()
    gen = playback.generation
    assert playback.push(chunk(0.5), generation=gen)
    playback.flush()
    assert client.cleared_player_count == 1
    pushed = len(client.pushed_audio)
    # a late chunk of the cut reply is dropped before it reaches the device
    assert playback.push(chunk(0.5), generation=gen) is False
    assert len(client.pushed_audio) == pushed
    assert playback.generation == gen + 1
    assert playback.push(chunk(0.1), generation=playback.generation)


def test_untagged_chunks_are_current() -> None:
    playback, client, _ = build()
    assert playback.push(chunk(0.1))
    assert len(client.pushed_audio) == 1


def test_the_stream_reopens_only_after_the_tail() -> None:
    playback, _, clock = build()
    assert playback.listen_again_at() == 0.0  # nothing played, nothing to wait for
    t0 = clock()
    playback.push(chunk(1.0))
    assert abs(playback.listen_again_at() - (t0 + 1.0 + TAIL_S)) < 1e-6


def test_back_to_back_chunks_queue_one_after_another() -> None:
    playback, _, clock = build()
    t0 = clock()
    playback.push(chunk(1.0))
    playback.push(chunk(1.0))  # pushed at once, plays after the first
    assert abs(playback.listen_again_at() - (t0 + 2.0 + TAIL_S)) < 1e-6


def test_a_flush_ends_the_tail_at_the_cut_not_at_the_queued_audio() -> None:
    playback, _, clock = build()
    t0 = clock()
    playback.push(chunk(3.0))
    clock.advance(0.5)
    playback.flush()
    assert abs(playback.listen_again_at() - (t0 + 0.5 + TAIL_S)) < 1e-6
    assert playback.pushed_duration_s() == 3.0  # the heard prefix stays in the ledger


class OneShotEngine:
    def __init__(self, tags: list[str | None]) -> None:
        self.tags = list(tags)
        self.begins = 0

    def begin(self) -> None:
        self.begins += 1

    def accept(self, block):
        return self.tags.pop(0) if self.tags else None

    def finish(self):
        return None


def test_the_keyword_stop_detector_fires_on_stop_only() -> None:
    block = np.zeros(512, np.float32)
    engine = OneShotEngine([None, "@play_music", "@stop"])
    det = KeywordStopDetector(engine)
    assert [det.accept(block) for _ in range(3)] == [False, False, True]
    det.reset()
    assert engine.begins == 2


def test_open_mic_bleed_gate() -> None:
    assert talk_over(0.5, 0.2, 0.1) is False  # inside the 250 ms grace
    assert talk_over(0.05, 0.2, 1.0) is False  # below 1.6 x 0.4 x 0.2 + 0.01 = 0.138
    assert talk_over(0.2, 0.2, 1.0) is True
    assert BLEED_GRACE_S == 0.25
