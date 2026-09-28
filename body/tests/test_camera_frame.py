"""The fixture-backed `Camera.get_frame()` path added alongside
`docs/dev/design-vision-still-image-2026-09-28.md` - the still-image
call's own design note names this as the first real prerequisite: no
deterministic test of a future capture flow was possible while the
fake always returned `None`."""

from __future__ import annotations

import numpy as np
import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.hal.errors import BodyLost


def test_default_construction_returns_none_unchanged():
    client = FakeReachyMiniClient()

    assert client.get_frame() is None


def test_a_given_frame_is_returned_exactly_not_a_copy_or_a_mock():
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    frame[0, 0] = (255, 0, 0)
    client = FakeReachyMiniClient(camera_frame=frame)

    returned = client.get_frame()

    assert returned is frame
    assert returned.dtype == np.uint8
    assert returned.shape == (64, 64, 3)
    assert tuple(returned[0, 0]) == (255, 0, 0)


def test_get_frame_raises_body_lost_after_disconnect():
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    client = FakeReachyMiniClient(camera_frame=frame)
    client.simulate_disconnect()

    with pytest.raises(BodyLost):
        client.get_frame()
