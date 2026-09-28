"""`recognize_face`'s own orchestration (detect -> align -> embed ->
match), against scripted stand-ins for the three real components - no
real model loaded, matching the deterministic-by-default rule; each
piece already has its own real-model-adjacent tests (`test_vision_
detect.py`, `test_vision_align.py`'s numpy math, a live sanity check
already run once by hand against the real SFace model this session)."""

from __future__ import annotations

import numpy as np

from maipai_body.vision.detect import FiveLandmarks
from maipai_body.vision.gallery import FaceVerdict
from maipai_body.vision.recognize import recognize_face


class _StubDetector:
    def __init__(self, faces: list[FiveLandmarks]) -> None:
        self._faces = faces
        self.detect_calls: list[np.ndarray] = []

    def detect(self, frame_bgr: np.ndarray) -> list[FiveLandmarks]:
        self.detect_calls.append(frame_bgr)
        return self._faces


class _StubEmbedder:
    def __init__(self, embedding: np.ndarray) -> None:
        self._embedding = embedding
        self.embed_calls: list[np.ndarray] = []

    def embed(self, aligned_bgr: np.ndarray) -> np.ndarray:
        self.embed_calls.append(aligned_bgr)
        return self._embedding


class _StubGallery:
    def __init__(self, verdict: FaceVerdict) -> None:
        self._verdict = verdict
        self.identify_calls: list[np.ndarray] = []

    def identify(self, embedding: np.ndarray) -> FaceVerdict:
        self.identify_calls.append(embedding)
        return self._verdict


_A_FACE = FiveLandmarks(
    bbox=(0, 0, 50, 50),
    right_eye=(15, 20),
    left_eye=(35, 20),
    nose=(25, 30),
    right_mouth=(18, 40),
    left_mouth=(32, 40),
)


def test_no_face_in_frame_returns_none_without_touching_embed_or_match():
    detector = _StubDetector(faces=[])
    embedder = _StubEmbedder(embedding=np.zeros(128, dtype=np.float32))
    gallery = _StubGallery(verdict=FaceVerdict(person_id=None, level="unknown", score=0.0))
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    result = recognize_face(frame, detector=detector, embedder=embedder, gallery=gallery)

    assert result is None
    assert embedder.embed_calls == []
    assert gallery.identify_calls == []


def test_a_detected_face_flows_through_align_embed_and_match():
    embedding = np.arange(128, dtype=np.float32)
    verdict = FaceVerdict(person_id="sage", level="tentative", score=0.91)
    detector = _StubDetector(faces=[_A_FACE])
    embedder = _StubEmbedder(embedding=embedding)
    gallery = _StubGallery(verdict=verdict)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    result = recognize_face(frame, detector=detector, embedder=embedder, gallery=gallery)

    assert result is verdict
    assert len(embedder.embed_calls) == 1
    # The embedder must have received a real (112, 112, 3) aligned crop,
    # not the raw frame passed straight through.
    assert embedder.embed_calls[0].shape == (112, 112, 3)
    assert len(gallery.identify_calls) == 1
    np.testing.assert_array_equal(gallery.identify_calls[0], embedding)


def test_only_the_first_detected_face_is_scored():
    second_face = FiveLandmarks(
        bbox=(60, 60, 50, 50),
        right_eye=(75, 80),
        left_eye=(95, 80),
        nose=(85, 90),
        right_mouth=(78, 100),
        left_mouth=(92, 100),
    )
    detector = _StubDetector(faces=[_A_FACE, second_face])
    embedder = _StubEmbedder(embedding=np.zeros(128, dtype=np.float32))
    gallery = _StubGallery(verdict=FaceVerdict(person_id=None, level="unknown", score=0.0))
    frame = np.zeros((150, 150, 3), dtype=np.uint8)

    recognize_face(frame, detector=detector, embedder=embedder, gallery=gallery)

    assert len(embedder.embed_calls) == 1


def test_recognize_face_is_offline_and_deterministic_for_a_fixed_frame():
    """No network, no real model - the same frame and stubs must
    produce the exact same result every call."""
    detector = _StubDetector(faces=[_A_FACE])
    embedder = _StubEmbedder(embedding=np.ones(128, dtype=np.float32))
    verdict = FaceVerdict(person_id="bramble", level="tentative", score=0.8)
    gallery = _StubGallery(verdict=verdict)
    frame = np.random.default_rng(42).integers(0, 255, (100, 100, 3), dtype=np.uint8)

    first = recognize_face(frame, detector=detector, embedder=embedder, gallery=gallery)
    second = recognize_face(frame, detector=detector, embedder=embedder, gallery=gallery)

    assert first == second == verdict
