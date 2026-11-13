"""The robot's own fast pass of Look: YOLOX-nano names the household things in one picture.

LOOK-01 (home `docs/design/look-component-2026-10-22.md`) made this the one detector for "what is
in a picture"; the owner's 2026-11-12 ruling runs it on the robot too, on the same frames the face
detector sees, so the body knows where a person is even when no face is in view (an arm or a
torso at desk distance) and can answer "what do you see" at once. The model is the shared robot
asset ``yolox-nano-0_1_1rc0`` (Apache-2.0, Megvii-BaseDetection/YOLOX 0.1.1rc0), synced from
Home by digest like YuNet, never vendored. The decode is the Stack's (`look_core.py`): letterbox
to 416 padded with 114, raw BGR float32, grid and stride decode, per-class NMS. Pictures are
judged in memory; only labels, scores and boxes come out, and nothing here logs a label.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from maipai_body.vision.yunet import _nms

logger = logging.getLogger("maipai_body.vision.look_fast")

INPUT = 416
_STRIDES = (8, 16, 32)
SCORE_THRESHOLD = 0.35  # the Stack's threshold for naming a thing
NMS_THRESHOLD = 0.45
PAD = 114.0
PERSON = "person"

COCO = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
    "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
    "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors",
    "teddy bear", "hair drier", "toothbrush",
)  # fmt: skip
# The spec's look-vocabulary `detector_classes` (the 42 things worth naming in a home). Read from
# the pinned spec when it is on this machine; this copy is the fallback for a bundle without it,
# and a test keeps the two equal.
_HOUSEHOLD_FALLBACK = (
    "person", "chair", "couch", "potted plant", "bed", "dining table", "tv", "laptop", "cell phone",
    "book", "bottle", "cup", "clock", "vase", "cat", "dog", "backpack", "handbag", "umbrella",
    "bowl", "refrigerator", "microwave", "oven", "sink", "toaster", "keyboard", "mouse", "remote",
    "scissors", "teddy bear", "bench", "suitcase", "wine glass", "fork", "knife", "spoon", "banana",
    "apple", "orange", "sandwich", "pizza", "cake",
)  # fmt: skip


def household_classes(spec_dir: Path | None = None) -> tuple[str, ...]:
    """The household vocabulary's detector classes from the pinned spec, else the fallback."""
    try:
        if spec_dir is None:
            from maipai_body.robot.api import default_spec_dir

            spec_dir = default_spec_dir()
        raw = json.loads((spec_dir / "vocab" / "look-vocabulary.json").read_text("utf-8"))
        classes = tuple(str(name) for name in raw["detector_classes"])
        if classes and all(name in COCO for name in classes):
            return classes
    except (OSError, KeyError, TypeError, ValueError):
        pass
    return _HOUSEHOLD_FALLBACK


@dataclass(frozen=True)
class Detection:
    """One thing in the picture; the box is x, y, width, height as shares of the frame (0 to 1)."""

    label: str
    score: float
    box: tuple[float, float, float, float]

    @property
    def centre_x(self) -> float:
        return self.box[0] + self.box[2] / 2

    @property
    def top(self) -> float:
        return self.box[1]

    @property
    def area(self) -> float:
        return self.box[2] * self.box[3]


def letterbox(frame_bgr: npt.NDArray[np.uint8]) -> tuple[npt.NDArray[np.float32], float]:
    """The picture scaled into the 416 square, padded with 114; returns the blob and the scale."""
    height, width = frame_bgr.shape[:2]
    scale = min(INPUT / height, INPUT / width)
    new_h, new_w = max(1, round(height * scale)), max(1, round(width * scale))
    rows = np.minimum((np.arange(new_h) / scale).astype(np.int32), height - 1)
    cols = np.minimum((np.arange(new_w) / scale).astype(np.int32), width - 1)
    canvas = np.full((INPUT, INPUT, 3), PAD, dtype=np.float32)
    canvas[:new_h, :new_w] = frame_bgr[rows][:, cols]
    return canvas.transpose(2, 0, 1)[np.newaxis], scale


def _grids() -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
    cells, strides = [], []
    for stride in _STRIDES:
        size = INPUT // stride
        yy, xx = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
        cells.append(np.stack([xx, yy], axis=-1).reshape(-1, 2))
        strides.append(np.full((size * size, 1), stride))
    return (
        np.concatenate(cells).astype(np.float32),
        np.concatenate(strides).astype(np.float32),
    )


_GRID, _STRIDE = _grids()


def decode(
    raw: npt.NDArray[np.float32],
    scale: float,
    width: int,
    height: int,
    *,
    classes: tuple[str, ...],
    score_threshold: float = SCORE_THRESHOLD,
) -> list[Detection]:
    """Detections from the model's (3549, 85) output, best score first, boxes as frame shares."""
    if raw.shape[0] != _GRID.shape[0]:
        raise ValueError(f"unsupported YOLOX output layout {raw.shape} for a {INPUT} input")
    xy = (raw[:, :2] + _GRID) * _STRIDE
    wh = np.exp(raw[:, 2:4]) * _STRIDE
    class_scores = raw[:, 4:5] * raw[:, 5:]
    best_class = class_scores.argmax(axis=1)
    score = class_scores[np.arange(len(best_class)), best_class]
    allowed = np.array(sorted(COCO.index(name) for name in classes))
    keep = np.flatnonzero((score >= score_threshold) & np.isin(best_class, allowed))
    results: list[Detection] = []
    for cls in np.unique(best_class[keep]):
        indexes = keep[best_class[keep] == cls]
        boxes = [
            (
                float(xy[i, 0] - wh[i, 0] / 2),
                float(xy[i, 1] - wh[i, 1] / 2),
                float(wh[i, 0]),
                float(wh[i, 1]),
            )
            for i in indexes
        ]
        for chosen in _nms(boxes, [float(score[i]) for i in indexes], NMS_THRESHOLD):
            x, y, w, h = boxes[chosen]
            left = max(0.0, min(width, x / scale))
            top = max(0.0, min(height, y / scale))
            right = max(left, min(width, (x + w) / scale))
            bottom = max(top, min(height, (y + h) / scale))
            results.append(
                Detection(
                    label=COCO[int(cls)],
                    score=float(score[indexes[chosen]]),
                    box=(
                        left / width,
                        top / height,
                        (right - left) / width,
                        (bottom - top) / height,
                    ),
                )
            )
    return sorted(results, key=lambda item: -item.score)


class YoloxDetector:
    """Name the things in BGR frames, confined to one CPU thread (the voice path comes first)."""

    def __init__(
        self,
        model_path: Path | str,
        *,
        classes: tuple[str, ...] | None = None,
        score_threshold: float = SCORE_THRESHOLD,
    ) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), options, providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name
        self._classes = classes or household_classes()
        self._score_threshold = score_threshold
        self.last_ms = 0.0  # how long the last detect took, for the minute line
        # The best person score of the last detect, before the threshold: how close a miss came.
        self.last_best_person = 0.0

    def detect(self, frame_bgr: npt.NDArray[np.uint8]) -> list[Detection]:
        started = time.perf_counter()
        height, width = frame_bgr.shape[:2]
        blob, scale = letterbox(frame_bgr)
        raw = self._session.run(None, {self._input_name: blob})[0][0]
        self.last_best_person = float((raw[:, 4] * raw[:, 5 + COCO.index(PERSON)]).max())
        found = decode(
            raw, scale, width, height, classes=self._classes, score_threshold=self._score_threshold
        )
        self.last_ms = (time.perf_counter() - started) * 1000.0
        return found


class LazyLookDetector:
    """A detector whose model arrives from the paired hub when first needed (as the face one).

    While the model is missing ``detect`` finds nothing and one WARNING per retry says what to
    do."""

    def __init__(
        self,
        load: Callable[[], Path],
        *,
        clock: Callable[[], float] = time.monotonic,
        retry_s: float | None = None,
    ) -> None:
        self._load = load
        self._clock = clock
        self._retry_s = retry_s
        self._retry_delays = (10.0, 30.0, 60.0, 300.0)
        self._failures = 0
        self._detector: YoloxDetector | None = None
        self._next_try = float("-inf")
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._detector is not None

    @property
    def last_ms(self) -> float:
        return self._detector.last_ms if self._detector is not None else 0.0

    @property
    def last_best_person(self) -> float:
        return self._detector.last_best_person if self._detector is not None else 0.0

    def detect(self, frame_bgr: npt.NDArray[np.uint8]) -> list[Detection]:
        detector = self._get()
        return detector.detect(frame_bgr) if detector is not None else []

    def _get(self) -> YoloxDetector | None:
        if self._detector is not None:
            return self._detector
        with self._lock:
            now = self._clock()
            if self._detector is not None or now < self._next_try:
                return self._detector
            try:
                self._detector = YoloxDetector(self._load())
                self._failures = 0
                logger.info("StackChan person and object detection is ready")
            except Exception as exc:
                delay = (
                    self._retry_delays[min(self._failures, len(self._retry_delays) - 1)]
                    if self._retry_s is None
                    else self._retry_s
                )
                self._failures += 1
                self._next_try = now + delay
                logger.warning(
                    "StackChan person detection is off: the look model is not available (%s). "
                    "Pair the robot with Home and let it sync its models; it will try again.",
                    exc,
                )
            return self._detector


# -- the LookResult objects and the spoken line ---------------------------------------------

MAX_SPOKEN_THINGS = 4
_NUMBERS = ("no", "a", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
_PLURALS = {"person": "people", "couch": "couches", "bench": "benches", "sandwich": "sandwiches"}


def objects_of(detections: list[Detection]) -> list[dict]:
    """The `LookResult.objects` shape: one entry per label with its count and best score, people
    first, then by score. The box kept is the largest one of that label (the nearest)."""
    by_label: dict[str, list[Detection]] = {}
    for item in detections:
        by_label.setdefault(item.label, []).append(item)
    objects = []
    for label, items in by_label.items():
        largest = max(items, key=lambda d: d.area)
        objects.append(
            {
                "label": label,
                "count": len(items),
                "score": max(d.score for d in items),
                "box": list(largest.box),
                "uncertain": max(d.score for d in items) < 0.5,
            }
        )
    return sorted(objects, key=lambda o: (o["label"] != PERSON, -o["score"]))


def _plural(label: str, count: int) -> str:
    if count == 1:
        return label
    return _PLURALS.get(label, label + "s")


def spoken_line(objects: list[dict]) -> str | None:
    """ "I see a person and a laptop." from the objects, at most four kinds; None for nothing."""
    parts = []
    for item in objects[:MAX_SPOKEN_THINGS]:
        count = int(item["count"])
        number = _NUMBERS[count] if count < len(_NUMBERS) else "many"
        parts.append(f"{number} {_plural(str(item['label']), count)}")
    if not parts:
        return None
    if len(parts) == 1:
        joined = parts[0]
    else:
        joined = ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"I see {joined}."


__all__ = [
    "COCO",
    "Detection",
    "LazyLookDetector",
    "YoloxDetector",
    "decode",
    "household_classes",
    "letterbox",
    "objects_of",
    "spoken_line",
]
