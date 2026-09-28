"""SFace's own 112x112 five-point alignment.

A line-for-line translation of OpenCV's own
`FaceRecognizerSF::alignCrop` (`modules/objdetect/src/face_recognize.cpp`,
the `4.x` branch, fetched and read directly 2026-09-28, not
reimplemented from a description) - the Umeyama similarity transform
(scale, rotation, translation, no shear) from a face's five detected
points to the fixed template SFace was trained against, then a
bilinear affine resample into a 112x112 crop. OpenCV itself is not a
dependency here (`design-face-recognition-models-2026-09-28.md`
section 3: "not added... for one affine warp"), and the design's own
"dependencies added: none" (section 6) means `scipy` isn't reached for
either - only `numpy`, already a base dependency, unlike `scipy`
(`voice`-extra only). Bilinear affine resampling is a short, fully
vectorized computation (map every output pixel through the inverse
transform, sample its four neighbors, blend by fractional position) -
"a maintained library for a solved problem" is the right call when the
problem needs one; this one is a few numpy lines, not a solved-problem
gap worth a new dependency for.

Point order (both the template and every `src` this module takes):
right eye, left eye, nose, right mouth corner, left mouth corner -
OpenCV's own docstring order, matching `FaceDetector`'s own five
`kps_*` values once `detect.py` decodes all five instead of three.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

CROP_SIZE = 112

# OpenCV's own hardcoded destination template, `getSimilarityTransformMatrix`'s
# `dst` array, in (x, y) pixel coordinates at a 112x112 crop.
_TEMPLATE = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float64,
)
# OpenCV's own precomputed constant, not recomputed from _TEMPLATE at
# call time (its source does the same, presumably for speed) - equal
# to _TEMPLATE.mean(axis=0) to four decimal places, kept as the exact
# literal so this module reproduces its arithmetic bit-for-bit, not
# just to the same rounding.
_TEMPLATE_MEAN = np.array([56.0262, 71.9008], dtype=np.float64)


def similarity_transform(src: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """The 2x3 affine matrix mapping `src` (5, 2) onto the SFace
    template, via the Umeyama method with scale - OpenCV's own
    `getSimilarityTransformMatrix`, translated line for line."""
    src = np.asarray(src, dtype=np.float64)
    if src.shape != (5, 2):
        raise ValueError(f"expected 5 (x, y) points, got shape {src.shape}")

    src_mean = src.mean(axis=0)
    src_demean = src - src_mean
    dst_demean = _TEMPLATE - _TEMPLATE_MEAN

    # A[i, j] = mean_k(dst_demean[k, i] * src_demean[k, j]) - the same
    # index order the C++ source builds A00..A11 in, not the more
    # usual dst_demean.T @ src_demean / n (identical here since it's
    # exactly that expression, spelled out the way the source spells
    # it so a future reader can line the two up).
    a = (dst_demean.T @ src_demean) / 5.0

    u, s, vt = np.linalg.svd(a)
    d = np.ones(2)
    if np.linalg.det(a) < 0:
        d[1] = -1.0

    rank = int(np.sum(s > s.max() * 2 * np.finfo(np.float32).tiny))
    det_u_vt = np.linalg.det(u) * np.linalg.det(vt)
    if rank == 1:
        if det_u_vt > 0:
            t = u @ vt
        else:
            d_temp = d.copy()
            d_temp[1] = -1.0
            t = u @ np.diag(d_temp) @ vt
    else:
        t = u @ np.diag(d) @ vt

    var_src = np.sum(src_demean**2, axis=0).sum() / 5.0
    scale = (1.0 / var_src) * (s[0] * d[0] + s[1] * d[1])

    translation = _TEMPLATE_MEAN - scale * (t @ src_mean)
    rotation_scaled = t * scale

    return np.hstack([rotation_scaled, translation.reshape(2, 1)])


def align_crop(
    frame_bgr: npt.NDArray[np.uint8], five_points: npt.NDArray[np.float64]
) -> npt.NDArray[np.uint8]:
    """Warp `frame_bgr` so the five given (x, y) points land on SFace's
    own template, cropped to (112, 112, 3) uint8 - the pixel-domain
    half of `alignCrop`. Bilinear, matching OpenCV's own `INTER_LINEAR`;
    a source pixel outside the frame contributes zero (`BORDER_CONSTANT`
    at 0, `warpAffine`'s own default) rather than being clamped to the
    edge, so a crop that reaches past the frame darkens instead of
    smearing the border - the honest result of a face too close to the
    frame's edge, not hidden."""
    matrix = similarity_transform(five_points)
    linear_inv = np.linalg.inv(matrix[:, :2])
    offset_inv = -linear_inv @ matrix[:, 2]

    # Every output pixel's (x, y), mapped back through the inverse
    # transform to find where it samples from in the source frame -
    # the forward transform maps src onto the template/output, so
    # warping needs its inverse (output -> src), the same relationship
    # `warpAffine` handles internally for a non-inverted matrix.
    xs, ys = np.meshgrid(
        np.arange(CROP_SIZE, dtype=np.float64), np.arange(CROP_SIZE, dtype=np.float64)
    )
    out_xy = np.stack([xs.ravel(), ys.ravel()], axis=1)
    src_xy = out_xy @ linear_inv.T + offset_inv
    src_x, src_y = src_xy[:, 0], src_xy[:, 1]

    height, width = frame_bgr.shape[:2]
    x0, y0 = np.floor(src_x).astype(np.int64), np.floor(src_y).astype(np.int64)
    fx, fy = (src_x - x0)[:, None], (src_y - y0)[:, None]

    def _sample(xi: npt.NDArray, yi: npt.NDArray) -> npt.NDArray[np.float64]:
        in_bounds = (xi >= 0) & (xi < width) & (yi >= 0) & (yi < height)
        values = frame_bgr[np.clip(yi, 0, height - 1), np.clip(xi, 0, width - 1)].astype(np.float64)
        values[~in_bounds] = 0.0
        return values

    blended = (
        _sample(x0, y0) * (1 - fx) * (1 - fy)
        + _sample(x0 + 1, y0) * fx * (1 - fy)
        + _sample(x0, y0 + 1) * (1 - fx) * fy
        + _sample(x0 + 1, y0 + 1) * fx * fy
    )
    return np.clip(blended, 0, 255).astype(np.uint8).reshape(CROP_SIZE, CROP_SIZE, -1)
