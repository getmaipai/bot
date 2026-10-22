"""Face detection with the pinned YuNet model on ONNX Runtime, without the Reachy SDK or OpenCV.

The model is the pinned shared asset ``yunet-2026may`` (MIT, an unmodified redistribution of the
OpenCV Zoo model by Wei Wu, Hanyang Peng and Shiqi Yu). Frames are decoded and judged in memory;
only boxes and landmarks come out, nothing is stored. The pre- and post-processing follows the
decoding in ``reachy_mini.vision.face_detector`` (Apache-2.0, Pollen Robotics), written out here so
the hub bundle needs no extra package.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

logger = logging.getLogger("maipai_body.vision.yunet")

_STRIDES = (8, 16, 32)
_MAX_STRIDE = 32
MAX_INPUT_WIDTH = 320  # wider frames are sampled down before detection


@dataclass(frozen=True)
class Face:
    """A face in pixel coordinates of the frame given to ``detect``."""

    bbox: tuple[float, float, float, float]  # x, y, width, height
    right_eye: tuple[float, float]
    left_eye: tuple[float, float]
    nose: tuple[float, float]
    score: float = 0.0


def _nms(
    boxes: list[tuple[float, float, float, float]], scores: list[float], iou_threshold: float
) -> list[int]:
    """Greedy non-maximum suppression; kept indices, best score first."""
    if not boxes:
        return []
    b = np.array(boxes, dtype=np.float32)
    x1, y1 = b[:, 0], b[:, 1]
    x2, y2 = b[:, 0] + b[:, 2], b[:, 1] + b[:, 3]
    area = b[:, 2] * b[:, 3]
    order = np.array(scores, dtype=np.float32).argsort()[::-1]
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        w = np.clip(np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]), 0.0, None)
        h = np.clip(np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]), 0.0, None)
        inter = w * h
        union = np.maximum(area[i] + area[rest] - inter, 1e-6)
        order = rest[inter / union <= iou_threshold]
    return keep


class YuNetDetector:
    """Detect faces in BGR frames, confined to one CPU thread."""

    def __init__(
        self,
        model_path: Path | str,
        *,
        score_threshold: float = 0.6,
        nms_threshold: float = 0.3,
    ) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1  # one thread: it must not starve the voice path
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), options, providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name
        self._output_names = [o.name for o in self._session.get_outputs()]
        self._score_threshold = score_threshold
        self._nms_threshold = nms_threshold
        # The best score of the last detect, before the threshold: how close a miss came.
        self.last_best_score = 0.0

    def detect(self, frame_bgr: npt.NDArray[np.uint8]) -> list[Face]:
        """Every face in a BGR frame; coordinates are in the frame's own pixels."""
        height, width = frame_bgr.shape[:2]
        step = max(1, math.ceil(width / MAX_INPUT_WIDTH))
        if step > 1:
            frame_bgr = frame_bgr[::step, ::step]
        small_h, small_w = frame_bgr.shape[:2]
        padded_h = math.ceil(small_h / _MAX_STRIDE) * _MAX_STRIDE
        padded_w = math.ceil(small_w / _MAX_STRIDE) * _MAX_STRIDE
        if (padded_h, padded_w) != (small_h, small_w):
            padded = np.zeros((padded_h, padded_w, 3), dtype=frame_bgr.dtype)
            padded[:small_h, :small_w] = frame_bgr
            frame_bgr = padded
        blob = frame_bgr.astype(np.float32).transpose(2, 0, 1)[np.newaxis]
        outputs = dict(zip(self._output_names, self._session.run(None, {self._input_name: blob})))
        faces = self._decode(outputs, padded_w)
        if step == 1:
            return faces
        return [_scaled(face, step) for face in faces]

    def _decode(self, outputs: dict[str, npt.NDArray[np.float32]], width: int) -> list[Face]:
        boxes: list[tuple[float, float, float, float]] = []
        scores: list[float] = []
        faces: list[Face] = []
        best = 0.0
        for stride in _STRIDES:
            cls = outputs[f"cls_{stride}"][0, :, 0]
            obj = outputs[f"obj_{stride}"][0, :, 0]
            score = np.sqrt(np.clip(cls, 0.0, 1.0) * np.clip(obj, 0.0, 1.0))
            if score.size:
                best = max(best, float(score.max()))
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
            for k in range(idx.size):
                box = (float(cx[k] - w[k] / 2), float(cy[k] - h[k] / 2), float(w[k]), float(h[k]))
                boxes.append(box)
                scores.append(float(score[idx[k]]))
                faces.append(
                    Face(
                        bbox=box,
                        right_eye=(
                            float((col[k] + kps[k, 0]) * stride),
                            float((row[k] + kps[k, 1]) * stride),
                        ),
                        left_eye=(
                            float((col[k] + kps[k, 2]) * stride),
                            float((row[k] + kps[k, 3]) * stride),
                        ),
                        nose=(
                            float((col[k] + kps[k, 4]) * stride),
                            float((row[k] + kps[k, 5]) * stride),
                        ),
                        score=float(score[idx[k]]),
                    )
                )
        self.last_best_score = best
        return [faces[i] for i in _nms(boxes, scores, self._nms_threshold)]


def _scaled(face: Face, factor: int) -> Face:
    def point(p: tuple[float, float]) -> tuple[float, float]:
        return (p[0] * factor, p[1] * factor)

    x, y, w, h = face.bbox
    return Face(
        bbox=(x * factor, y * factor, w * factor, h * factor),
        right_eye=point(face.right_eye),
        left_eye=point(face.left_eye),
        nose=point(face.nose),
        score=face.score,
    )


class LazyFaceDetector:
    """A detector whose model arrives from the paired hub when first needed.

    ``load`` returns a model path or raises (the hub is unreachable, the asset is not synced yet).
    While the model is missing ``detect`` finds nothing and one WARNING per ``retry_s`` says what
    to do; the next try happens after that time, so a hub that comes back later is picked up."""

    def __init__(
        self,
        load: Callable[[], Path],
        *,
        clock: Callable[[], float] = time.monotonic,
        retry_s: float = 600.0,
    ) -> None:
        self._load = load
        self._clock = clock
        self._retry_s = retry_s
        self._detector: YuNetDetector | None = None
        self._next_try = float("-inf")
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._detector is not None

    @property
    def best_score(self) -> float:
        """The best score of the last detect, before the threshold (0 until the model loads)."""
        return self._detector.last_best_score if self._detector is not None else 0.0

    def detect(self, frame_bgr: npt.NDArray[np.uint8]) -> list[Face]:
        detector = self._get()
        return detector.detect(frame_bgr) if detector is not None else []

    def _get(self) -> YuNetDetector | None:
        if self._detector is not None:
            return self._detector
        with self._lock:
            now = self._clock()
            if self._detector is not None or now < self._next_try:
                return self._detector
            self._next_try = now + self._retry_s
            try:
                self._detector = YuNetDetector(self._load())
                logger.info("StackChan face detection is ready")
            except Exception as exc:
                logger.warning(
                    "StackChan face detection is off: the face model is not available (%s). "
                    "Pair the robot with Home and let it sync its models; it will try again.",
                    exc,
                )
            return self._detector
