"""JPEG decoding and the YuNet runner, without OpenCV or the Reachy SDK."""

from __future__ import annotations

import os
import time
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest

from maipai_body.vision.jpeg import decode_jpeg
from maipai_body.vision.yunet import Face, LazyFaceDetector, YuNetDetector, _nms

MODEL = Path(
    os.environ.get(
        "MAIPAI_TEST_YUNET_MODEL",
        "/private/tmp/claude-501/-Users-jessetorres-Developer-github-com-getmaipai-home/"
        "3d1e9a62-883b-438d-9f15-2e92eeaa0a10/scratchpad/yunet/face_detection_yunet_2026may.onnx",
    )
)
PINNED_SHA256 = "ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0"
needs_model = pytest.mark.skipif(
    not MODEL.is_file(), reason="the YuNet model is not on this machine"
)


def _jpeg(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    encoder = av.CodecContext.create("mjpeg", "w")
    encoder.width, encoder.height = width, height
    encoder.pix_fmt = "yuvj420p"
    encoder.time_base = Fraction(1, 25)
    encoder.options = {"qscale": "2"}
    encoder.open()
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:] = rgb
    frame = av.VideoFrame.from_ndarray(image, format="rgb24").reformat(format="yuvj420p")
    frame.pts = 0
    return b"".join(bytes(packet) for packet in encoder.encode(frame) + encoder.encode(None))


def test_a_jpeg_decodes_to_a_bgr_array_of_the_right_size():
    frame = decode_jpeg(_jpeg(320, 240, (250, 10, 10)))  # red
    assert frame.shape == (240, 320, 3) and frame.dtype == np.uint8
    blue, green, red = frame.reshape(-1, 3).mean(axis=0)
    assert red > 200 and blue < 60 and green < 60  # BGR order: red is the last channel


@pytest.mark.parametrize("data", [b"", b"not a jpeg", b"\xff\xd8\xff\xe0garbage"])
def test_a_broken_jpeg_says_so_in_plain_words(data):
    with pytest.raises(ValueError, match="capture another frame"):
        decode_jpeg(data)


def test_nms_keeps_the_best_of_overlapping_boxes():
    boxes = [(0.0, 0.0, 10.0, 10.0), (1.0, 1.0, 10.0, 10.0), (50.0, 50.0, 10.0, 10.0)]
    assert _nms(boxes, [0.9, 0.95, 0.8], 0.3) == [1, 2]
    assert _nms([], [], 0.3) == []


@needs_model
def test_the_model_file_is_the_pinned_one():
    import hashlib

    assert hashlib.sha256(MODEL.read_bytes()).hexdigest() == PINNED_SHA256


@needs_model
def test_decoding_finds_a_face_at_the_anchor_that_scores_high():
    detector = YuNetDetector(MODEL)
    width, height = 64, 64
    outputs = {}
    for stride in (8, 16, 32):
        n = (height // stride) * (width // stride)
        outputs[f"cls_{stride}"] = np.zeros((1, n, 1), np.float32)
        outputs[f"obj_{stride}"] = np.zeros((1, n, 1), np.float32)
        outputs[f"bbox_{stride}"] = np.zeros((1, n, 4), np.float32)
        outputs[f"kps_{stride}"] = np.zeros((1, n, 10), np.float32)
    # stride 8, column 3, row 2 of an 8-column grid: centre at ((3 + 0.5) * 8, (2 + 0.5) * 8)
    index = 2 * (width // 8) + 3
    outputs["cls_8"][0, index, 0] = 0.9
    outputs["obj_8"][0, index, 0] = 0.9
    outputs["bbox_8"][0, index] = [0.5, 0.5, np.log(2.0), np.log(3.0)]
    faces = detector._decode(outputs, width)
    assert len(faces) == 1
    x, y, w, h = faces[0].bbox
    assert (x + w / 2, y + h / 2) == pytest.approx((28.0, 20.0))
    assert (w, h) == pytest.approx((16.0, 24.0))


@needs_model
def test_a_plain_frame_has_no_face_and_wide_frames_are_sampled_down():
    detector = YuNetDetector(MODEL)
    assert detector.detect(np.full((240, 320, 3), 128, np.uint8)) == []
    assert detector.detect(np.full((480, 640, 3), 128, np.uint8)) == []


@needs_model
def test_it_agrees_with_the_reachy_detector_on_the_same_frames():
    reachy = pytest.importorskip("reachy_mini.vision.face_detector")
    rng = np.random.default_rng(7)
    ours = YuNetDetector(MODEL, score_threshold=0.05)
    theirs = reachy.FaceDetector.__new__(reachy.FaceDetector)
    theirs._session = ours._session
    theirs._input_name = ours._input_name
    theirs._output_names = ours._output_names
    theirs._score_threshold = 0.05
    theirs._nms_threshold = 0.3
    for _ in range(3):
        frame = rng.integers(0, 255, size=(240, 320, 3), dtype=np.uint8)
        mine = ours.detect(frame)
        other = theirs.detect(frame)
        assert [f.bbox for f in mine] == pytest.approx([f.bbox for f in other])
        assert [f.nose for f in mine] == pytest.approx([f.nose for f in other])


@needs_model
def test_the_detector_is_fast_enough_for_two_frames_a_second(capsys):
    detector = YuNetDetector(MODEL)
    frame = np.full((240, 320, 3), 90, np.uint8)
    detector.detect(frame)  # warm up
    started = time.perf_counter()
    for _ in range(30):
        detector.detect(frame)
    mean_ms = (time.perf_counter() - started) / 30 * 1000
    with capsys.disabled():
        print(f"\nYuNet 320x240 mean {mean_ms:.1f} ms per frame on this machine")
    assert mean_ms < 250  # two frames a second leaves a wide margin on any machine we ship to


def test_the_lazy_detector_finds_nothing_and_retries_later_when_the_model_is_missing(caplog):
    now = [0.0]
    attempts = []

    def load():
        attempts.append(1)
        raise RuntimeError("the hub has not synced it")

    lazy = LazyFaceDetector(load, clock=lambda: now[0], retry_s=600.0)
    frame = np.zeros((32, 32, 3), np.uint8)
    assert lazy.detect(frame) == [] and lazy.detect(frame) == []
    assert len(attempts) == 1 and not lazy.ready  # not asked again inside the retry time
    assert sum("face detection is off" in r.getMessage() for r in caplog.records) == 1
    now[0] = 601.0
    lazy.detect(frame)
    assert len(attempts) == 2


def test_the_lazy_detector_uses_ten_thirty_sixty_then_five_minute_backoff():
    now = [0.0]
    attempts = []

    def load():
        attempts.append(now[0])
        raise RuntimeError("not ready")

    lazy = LazyFaceDetector(load, clock=lambda: now[0])
    frame = np.zeros((8, 8, 3), np.uint8)
    now[0] = 0.0
    lazy.detect(frame)
    expected = [0.0]
    for delay in (10.0, 30.0, 60.0, 300.0):
        now[0] += delay - 0.1
        lazy.detect(frame)
        assert attempts == expected
        now[0] += 0.1
        lazy.detect(frame)
        expected.append(now[0])
        assert attempts == expected
    assert attempts == [0.0, 10.0, 40.0, 100.0, 400.0]


@needs_model
def test_the_lazy_detector_loads_the_model_once_it_is_available():
    lazy = LazyFaceDetector(lambda: MODEL)
    assert lazy.detect(np.full((64, 64, 3), 128, np.uint8)) == []
    assert lazy.ready


def test_face_has_the_fields_the_vision_bridge_reads():
    face = Face(bbox=(1.0, 2.0, 3.0, 4.0), right_eye=(0, 0), left_eye=(0, 0), nose=(0, 0))
    assert face.bbox == (1.0, 2.0, 3.0, 4.0)
