"""State frames: typed, ordered, and stamped on one monotonic clock."""

from __future__ import annotations

from maipai_body.hal.seam import StateFrame


def test_state_frames_are_typed_ordered_and_stamped_monotonically(body_client):
    feed = body_client.state_feed(frequency=10.0)
    try:
        frames = [next(iter(feed)) for _ in range(5)]
    finally:
        feed.close()

    for frame in frames:
        assert isinstance(frame, StateFrame)

    seqs = [frame.seq for frame in frames]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)

    stamps = [frame.t_received_ns for frame in frames]
    assert stamps == sorted(stamps), "stamps are not monotonically non-decreasing"
