"""Five-point face landmarks for alignment.

The vendored `reachy_mini.vision.face_detector.FaceDetector`'s own
`Face` dataclass keeps only three points (both eyes and the nose) -
enough to know a face is there and roughly where, RM-06's own job, but
short of SFace's own five-point alignment template (`align.py`). The
YuNet model's `kps_*` outputs already carry all ten values per anchor
(five points, checked in `_decode`'s own source: indices 0-1 right
eye, 2-3 left eye, 4-5 nose - the same order this module reads
6-7/8-9 from for the two mouth corners, YuNet's own standard order).

This subclasses `FaceDetector` and overrides `_decode` rather than
editing the vendored file (`CLAUDE.md`: "the kit wraps and composes,
it does not fork" - the same rule applied to a vendored driver, not
just UI). The base `_decode`'s own per-anchor loop has to be
reproduced, not called and extended, since the raw `kps`/`col`/`row`
values it decodes from are local to that loop and discarded once
`Face` is built - there is no seam to hook a fifth and sixth point
onto after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from reachy_mini.vision.face_detector import FaceDetector, _nms

_STRIDES = (8, 16, 32)


@dataclass(frozen=True)
class FiveLandmarks:
    """A detected face's five alignment points, in the order SFace's
    own template expects: right eye, left eye, nose, right mouth
    corner, left mouth corner."""

    bbox: tuple[float, float, float, float]
    right_eye: tuple[float, float]
    left_eye: tuple[float, float]
    nose: tuple[float, float]
    right_mouth: tuple[float, float]
    left_mouth: tuple[float, float]

    def as_points(self) -> npt.NDArray[np.float64]:
        """The five points as a (5, 2) array - `align.similarity_transform`'s own input shape."""
        return np.array(
            [self.right_eye, self.left_eye, self.nose, self.right_mouth, self.left_mouth],
            dtype=np.float64,
        )


class FiveLandmarkDetector(FaceDetector):
    """`FaceDetector`, with all five YuNet landmarks kept instead of
    three. Everything else (the model, the score/NMS thresholds, the
    padding and resize in `detect()`) is inherited unchanged."""

    def _decode(
        self, outputs: dict[str, npt.NDArray[np.float32]], width: int
    ) -> list[FiveLandmarks]:
        boxes: list[tuple[float, float, float, float]] = []
        scores: list[float] = []
        faces: list[FiveLandmarks] = []
        for stride in _STRIDES:
            cls = outputs[f"cls_{stride}"][0, :, 0]
            obj = outputs[f"obj_{stride}"][0, :, 0]
            score = np.sqrt(np.clip(cls, 0.0, 1.0) * np.clip(obj, 0.0, 1.0))
            idx = np.nonzero(score >= self._score_threshold)[0]
            if idx.size == 0:
                continue
            bbox = outputs[f"bbox_{stride}"][0][idx]
            kps = outputs[f"kps_{stride}"][0][idx]
            cols = width // stride
            col = (idx % cols).astype(np.float32)
            row = (idx // cols).astype(np.float32)
            cx = (col + bbox[:, 0]) * stride
            cy = (row + bbox[:, 1]) * stride
            w = np.exp(bbox[:, 2]) * stride
            h = np.exp(bbox[:, 3]) * stride

            def point(k: int, i: int) -> tuple[float, float]:
                return (
                    float((col[k] + kps[k, i]) * stride),
                    float((row[k] + kps[k, i + 1]) * stride),
                )

            for k in range(idx.size):
                box = (
                    float(cx[k] - w[k] / 2),
                    float(cy[k] - h[k] / 2),
                    float(w[k]),
                    float(h[k]),
                )
                boxes.append(box)
                scores.append(float(score[idx[k]]))
                faces.append(
                    FiveLandmarks(
                        bbox=box,
                        right_eye=point(k, 0),
                        left_eye=point(k, 2),
                        nose=point(k, 4),
                        right_mouth=point(k, 6),
                        left_mouth=point(k, 8),
                    )
                )
        return [faces[i] for i in _nms(boxes, scores, self._nms_threshold)]
