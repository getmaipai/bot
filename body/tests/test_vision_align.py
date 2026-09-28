"""FACE-01's own alignment math, checked against known transforms -
not cross-checked against a real OpenCV install (not a dependency
here), so correctness is proven from first principles: the transform
this module computes must actually map its input points onto SFace's
template, which is the one thing `similarity_transform` is for."""

from __future__ import annotations

import numpy as np
import pytest

from maipai_body.vision.align import _TEMPLATE, CROP_SIZE, align_crop, similarity_transform


def _apply(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Apply a 2x3 affine matrix to (n, 2) points, the same convention
    `similarity_transform`'s own matrix uses."""
    return points @ matrix[:, :2].T + matrix[:, 2]


def test_the_template_mapped_to_itself_is_near_identity():
    matrix = similarity_transform(_TEMPLATE)

    assert matrix[:, :2] == pytest.approx(np.eye(2), abs=1e-3)
    assert matrix[:, 2] == pytest.approx(np.zeros(2), abs=1e-2)


def test_a_scaled_rotated_translated_src_maps_back_onto_the_template():
    """The real correctness property: whatever `src` five points are
    given, the computed transform must land them on the template -
    checked here with a src built by applying a KNOWN similarity
    transform (scale 1.7, rotate 20 degrees, translate) to the
    template, then inverting: `similarity_transform` never sees that
    known transform, only its output, and must recover an inverse that
    actually works, not just one that looks plausible."""
    scale = 1.7
    theta = np.deg2rad(20.0)
    rotation = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    translation = np.array([15.0, -8.0])

    # src is what a detector would report if the template were embedded
    # in a frame under this known transform: src = scale*R*template + t.
    src = (scale * rotation @ _TEMPLATE.T).T + translation

    matrix = similarity_transform(src)
    recovered = _apply(matrix, src)

    # 1e-3, not 1e-6: `_TEMPLATE_MEAN` is OpenCV's own hardcoded,
    # four-decimal-rounded constant, not the exact mean of `_TEMPLATE`
    # computed at call time - a few 1e-5 pixels of noise from that
    # rounding is expected and irrelevant at a 112x112 crop's scale,
    # not evidence of a wrong transform.
    assert recovered == pytest.approx(_TEMPLATE, abs=1e-3)


def test_a_reflected_src_still_yields_a_proper_rotation_not_a_mirror():
    """The rank/determinant branch (det(A) < 0) exists to stop a
    reflected point set from producing a mirrored transform - it does
    NOT mean a genuine reflection can be exactly undone by a similarity
    transform (a real rotation+scale+translation has no reflection in
    it at all, so there is no exact answer to recover for input that
    truly is mirrored; forcing one here would be the wrong test, not a
    correctness bar this code can meet). What the branch guarantees:
    the rotation part it returns stays a proper rotation (determinant
    +1, orthogonal) even when fed a reflected input, rather than
    silently returning an improper one."""
    reflection = np.array([[-1.0, 0.0], [0.0, 1.0]])
    src = (reflection @ _TEMPLATE.T).T + np.array([5.0, 5.0])

    matrix = similarity_transform(src)
    linear = matrix[:, :2]
    scale = np.sqrt(np.abs(np.linalg.det(linear)))
    rotation = linear / scale

    assert np.linalg.det(rotation) == pytest.approx(1.0, abs=1e-6)
    assert rotation @ rotation.T == pytest.approx(np.eye(2), abs=1e-6)


def test_similarity_transform_rejects_the_wrong_point_count():
    with pytest.raises(ValueError, match="5"):
        similarity_transform(np.zeros((4, 2)))


def test_align_crop_returns_a_112x112_uint8_frame():
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    # Five points spread out so the similarity transform is well-posed
    # (not degenerate/collinear).
    points = np.array([[80, 90], [120, 90], [100, 110], [85, 130], [115, 130]], dtype=np.float64)

    crop = align_crop(frame, points)

    assert crop.shape == (CROP_SIZE, CROP_SIZE, 3)
    assert crop.dtype == np.uint8


def test_align_crop_of_the_template_points_themselves_is_close_to_identity():
    """Feeding the template's own points back in should crop
    approximately the same 112x112 region unchanged (scale ~1, no
    rotation) - a bright marker placed at a template point should
    still be near that same pixel in the output."""
    frame = np.zeros((112, 112, 3), dtype=np.uint8)
    marker_xy = (38, 52)  # near the right-eye template point
    frame[marker_xy[1], marker_xy[0]] = (255, 255, 255)

    crop = align_crop(frame, _TEMPLATE)

    # The bright marker should still land within a few pixels of where
    # it started, not have moved across the whole crop.
    bright = np.argwhere(crop[:, :, 0] > 200)
    assert bright.size > 0
    nearest = bright[np.argmin(np.sum((bright - [marker_xy[1], marker_xy[0]]) ** 2, axis=1))]
    assert abs(int(nearest[0]) - marker_xy[1]) <= 3
    assert abs(int(nearest[1]) - marker_xy[0]) <= 3
