"""The robot's own fast Look pass: YOLOX-nano decode, the lazy loader, the spoken line."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import numpy as np
import pytest

from maipai_body.vision.look_fast import (
    _GRID,
    _HOUSEHOLD_FALLBACK,
    _STRIDE,
    COCO,
    INPUT,
    Detection,
    LazyLookDetector,
    YoloxDetector,
    decode,
    household_classes,
    letterbox,
    objects_of,
    spoken_line,
)
from maipai_body.vision.models import YOLOX_NANO

MODEL = Path(
    os.environ.get(
        "MAIPAI_TEST_YOLOX_MODEL", "/usr/local/maipai-home/data/models/robot-assets/yolox_nano.onnx"
    )
)
needs_model = pytest.mark.skipif(
    not MODEL.is_file(), reason="the YOLOX model is not on this machine"
)


def test_the_pin_is_the_shared_look_detector():
    assert YOLOX_NANO.id == "yolox-nano-0_1_1rc0"
    assert YOLOX_NANO.file == "yolox_nano.onnx"
    assert YOLOX_NANO.sha256 == "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d"


def test_the_household_classes_are_the_specs_and_the_fallback_matches():
    spec_dir = Path(os.environ.get("MAIPAI_SPEC_DIR", ""))
    if not (spec_dir / "vocab" / "look-vocabulary.json").is_file():
        pytest.skip("pinned spec source not found (set MAIPAI_SPEC_DIR)")
    spec = json.loads((spec_dir / "vocab" / "look-vocabulary.json").read_text())
    assert tuple(spec["detector_classes"]) == _HOUSEHOLD_FALLBACK == household_classes(spec_dir)
    assert household_classes(Path("/nowhere")) == _HOUSEHOLD_FALLBACK
    assert all(name in COCO for name in _HOUSEHOLD_FALLBACK) and COCO[0] == "person"


def test_letterbox_scales_a_320x240_frame_into_the_square_and_pads_the_rest():
    frame = np.full((240, 320, 3), 200, np.uint8)
    blob, scale = letterbox(frame)
    assert blob.shape == (1, 3, INPUT, INPUT) and blob.dtype == np.float32
    assert scale == pytest.approx(INPUT / 320)
    assert blob[0, 0, 0, 0] == 200.0 and blob[0, 0, INPUT - 1, 0] == 114.0  # padding below


def _raw_with(cell: int, cls: int, score: float, w_cells: float = 2.0, h_cells: float = 4.0):
    raw = np.zeros((_GRID.shape[0], 85), np.float32)
    raw[:, 4] = 0.0
    raw[cell, 0:2] = 0.5  # centre of the cell
    raw[cell, 2] = np.log(w_cells)
    raw[cell, 3] = np.log(h_cells)
    raw[cell, 4] = 1.0
    raw[cell, 5 + cls] = score
    return raw


def test_decode_places_a_person_box_in_frame_shares_with_the_left_edge_negative_of_centre():
    # A stride-8 cell in the left third of the picture: cell (col 12, row 20) of the 52x52 grid.
    col, row = 12, 20
    cell = row * (INPUT // 8) + col
    width, height = 320, 240
    scale = min(INPUT / height, INPUT / width)
    raw = _raw_with(cell, COCO.index("person"), 0.9)
    found = decode(raw, scale, width, height, classes=("person", "chair"))
    assert [d.label for d in found] == ["person"]
    person = found[0]
    expected_cx = ((col + 0.5) * 8 / scale) / width
    assert person.centre_x == pytest.approx(expected_cx, abs=0.01)
    assert person.centre_x < 0.5 and 0 <= person.top <= 1 and person.score == pytest.approx(0.9)
    assert all(0.0 <= v <= 1.0 for v in person.box)


def test_decode_drops_low_scores_and_classes_outside_the_vocabulary():
    cell = 100
    width, height, scale = 320, 240, INPUT / 320
    low = _raw_with(cell, COCO.index("person"), 0.2)
    assert decode(low, scale, width, height, classes=("person",)) == []
    other = _raw_with(cell, COCO.index("zebra"), 0.95)
    assert decode(other, scale, width, height, classes=("person", "chair")) == []
    assert decode(other, scale, width, height, classes=COCO)[0].label == "zebra"


def test_decode_refuses_an_output_of_the_wrong_shape():
    with pytest.raises(ValueError, match="unsupported YOLOX output layout"):
        decode(np.zeros((10, 85), np.float32), 1.0, 320, 240, classes=("person",))
    assert _STRIDE.shape[0] == _GRID.shape[0] == 3549


def test_objects_group_by_label_with_people_first_and_the_largest_box_kept():
    found = [
        Detection("chair", 0.8, (0.1, 0.5, 0.2, 0.3)),
        Detection("person", 0.6, (0.4, 0.2, 0.3, 0.8)),
        Detection("chair", 0.7, (0.7, 0.5, 0.1, 0.2)),
        Detection("person", 0.55, (0.0, 0.3, 0.1, 0.2)),
    ]
    objects = objects_of(found)
    assert [o["label"] for o in objects] == ["person", "chair"]
    assert objects[0]["count"] == 2 and objects[0]["box"] == [0.4, 0.2, 0.3, 0.8]
    assert objects[1]["count"] == 2 and objects[1]["score"] == pytest.approx(0.8)
    assert objects[0]["uncertain"] is False
    assert objects_of([Detection("cup", 0.4, (0, 0, 0.1, 0.1))])[0]["uncertain"] is True


@pytest.mark.parametrize(
    "objects, line",
    [
        ([], None),
        ([{"label": "person", "count": 1}], "I see a person."),
        (
            [{"label": "person", "count": 2}, {"label": "laptop", "count": 1}],
            "I see two people and a laptop.",
        ),
        (
            [
                {"label": "chair", "count": 3},
                {"label": "cup", "count": 1},
                {"label": "couch", "count": 2},
            ],
            "I see three chairs, a cup and two couches.",
        ),
    ],
)
def test_the_spoken_line_counts_things_in_plain_words(objects, line):
    assert spoken_line(objects) == line


def test_the_spoken_line_names_at_most_four_kinds():
    objects = [{"label": name, "count": 1} for name in ("person", "chair", "cup", "book", "vase")]
    assert spoken_line(objects) == "I see a person, a chair, a cup and a book."


def test_the_lazy_detector_finds_nothing_and_retries_later_when_the_model_is_missing(caplog):
    now = [0.0]
    attempts = []

    def load():
        attempts.append(1)
        raise RuntimeError("the hub has not synced it")

    lazy = LazyLookDetector(load, clock=lambda: now[0], retry_s=600.0)
    frame = np.zeros((32, 32, 3), np.uint8)
    assert lazy.detect(frame) == [] and lazy.detect(frame) == []
    assert len(attempts) == 1 and not lazy.ready and lazy.last_ms == 0.0
    assert sum("person detection is off" in r.getMessage() for r in caplog.records) == 1
    now[0] = 601.0
    lazy.detect(frame)
    assert len(attempts) == 2


@needs_model
def test_the_real_model_sees_nothing_in_a_flat_frame_and_is_fast(capsys):
    detector = YoloxDetector(MODEL)
    frame = np.full((240, 320, 3), 90, np.uint8)
    assert detector.detect(frame) == []
    started = time.perf_counter()
    for _ in range(20):
        detector.detect(frame)
    mean_ms = (time.perf_counter() - started) / 20 * 1000
    with capsys.disabled():
        print(f"\nYOLOX-nano 320x240 mean {mean_ms:.1f} ms per frame on this machine")
    assert mean_ms < 150 and detector.last_ms > 0


@needs_model
def test_the_lazy_detector_loads_the_real_model_once(caplog):
    caplog.set_level(logging.INFO, logger="maipai_body.vision.look_fast")
    lazy = LazyLookDetector(lambda: MODEL)
    assert not lazy.ready
    assert lazy.detect(np.zeros((240, 320, 3), np.uint8)) == []
    assert lazy.ready and lazy.last_ms > 0
    assert any("object detection is ready" in r.getMessage() for r in caplog.records)
