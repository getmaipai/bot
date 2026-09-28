"""`_to_blob`'s own preprocessing, checked directly - its own docstring
names the risk: a channel-order or scaling mistake here would not
crash, it would silently degrade every match this repo ever makes.
A review (2026-09-28) caught that this had no regression test at all,
only a one-off manual run against the real model - this closes that
gap without needing the real 38 MB model file."""

from __future__ import annotations

import numpy as np
import pytest

from maipai_body.vision.embed import CROP_SIZE, _to_blob


def test_to_blob_shape_and_dtype():
    frame = np.zeros((CROP_SIZE, CROP_SIZE, 3), dtype=np.uint8)

    blob = _to_blob(frame)

    assert blob.shape == (1, 3, CROP_SIZE, CROP_SIZE)
    assert blob.dtype == np.float32


def test_to_blob_swaps_bgr_to_rgb():
    """blobFromImage's own swapRB=true: channel 0 (blue, in a BGR
    frame) must land in the RGB blob's red slot, and vice versa - a
    flipped or missing swap here silently transposes every color a
    face's skin tone is read through, without ever raising."""
    frame = np.zeros((CROP_SIZE, CROP_SIZE, 3), dtype=np.uint8)
    frame[0, 0] = (10, 20, 30)  # BGR: blue=10, green=20, red=30

    blob = _to_blob(frame)

    # blob is NCHW: blob[0, channel, row, col].
    assert blob[0, 0, 0, 0] == pytest.approx(30.0)  # R channel <- the frame's red=30
    assert blob[0, 1, 0, 0] == pytest.approx(20.0)  # G channel <- green=20
    assert blob[0, 2, 0, 0] == pytest.approx(10.0)  # B channel <- the frame's blue=10


def test_to_blob_does_not_scale_to_0_1():
    """scalefactor=1 in the cited blobFromImage call: pixel values stay
    in their original 0-255 range, never divided by 255 - a "helpful"
    /255 normalization added later would silently wreck every score."""
    frame = np.full((CROP_SIZE, CROP_SIZE, 3), 200, dtype=np.uint8)

    blob = _to_blob(frame)

    assert blob.max() == pytest.approx(200.0)
    assert blob.max() > 1.0


def test_to_blob_transposes_hwc_to_chw():
    frame = np.zeros((CROP_SIZE, CROP_SIZE, 3), dtype=np.uint8)
    frame[5, 9] = (1, 2, 3)  # a single marked pixel at row=5, col=9

    blob = _to_blob(frame)

    # After the BGR->RGB swap, this pixel's R=3, G=2, B=1, at the same
    # (row, col) but now indexed as blob[0, channel, row, col].
    assert blob[0, 0, 5, 9] == pytest.approx(3.0)
    assert blob[0, 1, 5, 9] == pytest.approx(2.0)
    assert blob[0, 2, 5, 9] == pytest.approx(1.0)
    # Everywhere else stays zero - the transpose didn't scramble other pixels.
    assert blob[0, :, 0, 0].sum() == 0.0


def test_to_blob_rejects_the_wrong_shape():
    with pytest.raises(ValueError, match="112"):
        _to_blob(np.zeros((50, 50, 3), dtype=np.uint8))
