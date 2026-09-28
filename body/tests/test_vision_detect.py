"""`FiveLandmarkDetector._decode()` against synthetic YuNet outputs -
deterministic and offline (no real model download), the same
"drive the code with a scripted stand-in" habit as everywhere else in
this repo. Real-model coverage against a real frame is a separate,
explicitly-run bench, matching G2's own real-model test pattern."""

from __future__ import annotations

import numpy as np
import pytest

from maipai_body.vision.detect import FiveLandmarkDetector, FiveLandmarks


def _make_detector() -> FiveLandmarkDetector:
    # __init__ downloads the real model via hf_hub_download - not
    # wanted for a decode-only test, so the instance is built without
    # calling it, the same "construct without __init__" pattern used
    # when only one method needs isolating from an expensive setup.
    return FiveLandmarkDetector.__new__(FiveLandmarkDetector)


def _empty_stride_outputs(stride: int, cols: int, rows: int) -> dict:
    n = cols * rows
    return {
        f"cls_{stride}": np.zeros((1, n, 1), dtype=np.float32),
        f"obj_{stride}": np.zeros((1, n, 1), dtype=np.float32),
    }


def test_decode_keeps_all_five_landmarks_not_just_three():
    detector = _make_detector()
    detector._score_threshold = 0.6
    detector._nms_threshold = 0.3

    width = 64  # cols = 64 // 32 = 2 at the stride under test
    outputs = {}
    outputs.update(_empty_stride_outputs(8, cols=8, rows=8))
    outputs.update(_empty_stride_outputs(16, cols=4, rows=4))

    # One real anchor at stride 32, col=0 row=0 (idx=0): a full-
    # confidence detection with distinct, checkable kps values.
    outputs["cls_32"] = np.ones((1, 1, 1), dtype=np.float32)
    outputs["obj_32"] = np.ones((1, 1, 1), dtype=np.float32)
    outputs["bbox_32"] = np.zeros((1, 1, 4), dtype=np.float32)  # cx=cy=0, w=h=32
    outputs["kps_32"] = np.array(
        [[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]], dtype=np.float32
    ).reshape(1, 1, 10)

    faces = detector._decode(outputs, width)

    assert len(faces) == 1
    face = faces[0]
    assert isinstance(face, FiveLandmarks)
    # point = kps_value * stride (col=row=0 here, so no offset term).
    assert face.right_eye == pytest.approx((0.1 * 32, 0.2 * 32))
    assert face.left_eye == pytest.approx((0.3 * 32, 0.4 * 32))
    assert face.nose == pytest.approx((0.5 * 32, 0.6 * 32))
    assert face.right_mouth == pytest.approx((0.7 * 32, 0.8 * 32))
    assert face.left_mouth == pytest.approx((0.9 * 32, 1.0 * 32))


def test_no_anchor_above_threshold_yields_no_faces():
    detector = _make_detector()
    detector._score_threshold = 0.6
    detector._nms_threshold = 0.3

    outputs = {}
    for stride, cols, rows in ((8, 8, 8), (16, 4, 4), (32, 2, 2)):
        outputs.update(_empty_stride_outputs(stride, cols, rows))

    assert detector._decode(outputs, width=64) == []


def test_as_points_returns_the_sface_template_order():
    face = FiveLandmarks(
        bbox=(0, 0, 10, 10),
        right_eye=(1.0, 2.0),
        left_eye=(3.0, 4.0),
        nose=(5.0, 6.0),
        right_mouth=(7.0, 8.0),
        left_mouth=(9.0, 10.0),
    )

    points = face.as_points()

    assert points.shape == (5, 2)
    assert points.dtype == np.float64
    np.testing.assert_array_equal(
        points, [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0], [9.0, 10.0]]
    )
