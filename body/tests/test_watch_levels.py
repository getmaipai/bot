"""FACE-WATCH-01: the always-on vision watch under watch levels, against
scripted stand-ins (a counting embedder, a scripted detector, a fake
camera) and a real `FaceGallery`. Rules under test (OWNER-ANSWERS 4):
enrolled only, a child needs a parent's enrolment, a teen must agree,
visitors are never recognised."""

from __future__ import annotations

import numpy as np

from maipai_body.vision.detect import FiveLandmarks
from maipai_body.vision.gallery import FaceGallery, FacePrint
from maipai_body.vision.watch import VisionWatch, read_cpu_temp_c, stricter

MODEL = "sface-2021dec"
SHA = "0ba9fbfa" + "0" * 56


def _face(x: float = 100.0, y: float = 80.0, size: float = 60.0) -> FiveLandmarks:
    return FiveLandmarks(
        bbox=(x, y, size, size),
        right_eye=(x + 0.3 * size, y + 0.35 * size),
        left_eye=(x + 0.7 * size, y + 0.35 * size),
        nose=(x + 0.5 * size, y + 0.55 * size),
        right_mouth=(x + 0.35 * size, y + 0.8 * size),
        left_mouth=(x + 0.65 * size, y + 0.8 * size),
    )


class _Camera:
    def __init__(self, shape=(480, 640, 3)) -> None:
        self.reads = 0
        self.shape = shape

    def get_frame(self):
        self.reads += 1
        return np.zeros(self.shape, dtype=np.uint8)


class _Detector:
    def __init__(self) -> None:
        self.faces: list[FiveLandmarks] = []
        self.seen_shapes: list[tuple[int, ...]] = []

    def detect(self, frame):
        self.seen_shapes.append(frame.shape)
        return list(self.faces)


class _Embedder:
    """Counts calls; returns whichever vector the test set."""

    def __init__(self) -> None:
        self.calls = 0
        self.vector = np.zeros(128, dtype=np.float32)

    def embed(self, aligned):
        self.calls += 1
        return self.vector.copy()


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _unit(i: int) -> np.ndarray:
    v = np.zeros(128, dtype=np.float32)
    v[i] = 1.0
    return v


def _gallery(*people: tuple[str, int, str]) -> FaceGallery:
    gallery = FaceGallery(MODEL, SHA)
    gallery.replace_all(
        FacePrint(
            id=f"print-{pid}",
            person_id=pid,
            model_id=MODEL,
            model_sha256=SHA,
            embedding=_unit(axis),
            watch=watch,  # type: ignore[arg-type]
        )
        for pid, axis, watch in people
    )
    return gallery


def _make(gallery: FaceGallery | None = None, level: str = "identify", **kwargs):
    camera, detector, embedder, clock = _Camera(), _Detector(), _Embedder(), _Clock()
    watch = VisionWatch(
        camera,
        detector,
        embedder,
        gallery or _gallery(),
        device_level=level,  # type: ignore[arg-type]
        clock=clock,
        **kwargs,
    )
    return watch, camera, detector, embedder, clock


def test_stricter_orders_off_below_presence_below_identify():
    assert stricter("identify", "presence") == "presence"
    assert stricter("off", "identify") == "off"
    assert stricter("identify", "identify") == "identify"


def test_off_never_reads_the_camera_and_releases_media_once():
    released: list[int] = []
    watch, camera, detector, _, clock = _make(level="off", release_media=lambda: released.append(1))
    detector.faces = [_face()]
    for _ in range(5):
        watch.step()
        clock.t += 0.2
    assert camera.reads == 0
    assert detector.seen_shapes == []
    assert watch.current().present == 0
    assert released == [1]


def test_presence_counts_faces_but_runs_no_embedding():
    watch, camera, detector, embedder, clock = _make(level="presence")
    detector.faces = [_face()]
    for _ in range(10):
        watch.step()
        clock.t += 0.2
    assert camera.reads == 10
    assert embedder.calls == 0
    snap = watch.current()
    assert snap.present == 1
    assert snap.verdict is not None and snap.verdict.person_id is None


def test_frame_is_resized_to_320x240_before_detection():
    watch, _, detector, _, _ = _make(level="presence")
    watch.step()
    assert detector.seen_shapes == [(240, 320, 3)]


def test_identify_names_an_enrolled_adult_with_identify_watch():
    watch, _, detector, embedder, _ = _make(_gallery(("person-adult1", 3, "identify")))
    detector.faces = [_face()]
    embedder.vector = _unit(3)
    watch.step()
    verdict = watch.current().verdict
    assert verdict is not None
    assert verdict.person_id == "person-adult1" and verdict.level == "tentative"


def test_guest_or_unenrolled_face_never_gets_an_id_even_near_threshold():
    # The guest has no print. A vector near an enrolled person's axis but
    # under the threshold must stay unknown, and nothing is retained.
    watch, _, detector, embedder, clock = _make(_gallery(("person-adult1", 3, "identify")))
    detector.faces = [_face()]
    near = _unit(3) * 0.30 + _unit(9) * 0.95
    embedder.vector = near.astype(np.float32)
    watch.step()
    verdict = watch.current().verdict
    assert verdict is not None and verdict.person_id is None and verdict.level == "unknown"
    assert embedder.calls == 1


def test_a_childs_print_gives_an_id_only_when_their_watch_is_identify():
    for person_watch, expect_id in (("identify", True), ("presence", False), ("off", False)):
        watch, _, detector, embedder, _ = _make(_gallery(("person-child01", 5, person_watch)))
        detector.faces = [_face()]
        embedder.vector = _unit(5)
        watch.step()
        verdict = watch.current().verdict
        assert verdict is not None
        assert (verdict.person_id == "person-child01") is expect_id, person_watch


def test_a_teens_print_gives_an_id_only_when_the_teens_own_watch_is_identify():
    for person_watch, expect_id in (("identify", True), ("presence", False)):
        watch, _, detector, embedder, _ = _make(_gallery(("person-teen001", 6, person_watch)))
        detector.faces = [_face()]
        embedder.vector = _unit(6)
        watch.step()
        verdict = watch.current().verdict
        assert verdict is not None
        assert (verdict.person_id == "person-teen001") is expect_id


def test_a_print_without_a_stated_watch_level_defaults_to_presence_only():
    gallery = FaceGallery(MODEL, SHA)
    gallery.replace_all(
        [FacePrint("p", "person-adult1", MODEL, SHA, _unit(1))]  # no watch given
    )
    watch, _, detector, embedder, _ = _make(gallery)
    detector.faces = [_face()]
    embedder.vector = _unit(1)
    watch.step()
    assert watch.current().verdict.person_id is None  # type: ignore[union-attr]


def test_a_close_tie_never_leaks_a_candidate_whose_watch_is_not_identify():
    gallery = _gallery(("person-adult1", 2, "identify"), ("person-child01", 3, "presence"))
    watch, _, detector, embedder, _ = _make(gallery)
    detector.faces = [_face()]
    embedder.vector = (_unit(2) + _unit(3)).astype(np.float32)
    watch.step()
    verdict = watch.current().verdict
    assert verdict is not None and verdict.person_id is None
    assert verdict.candidates == ()


def test_new_track_embeds_at_once_then_every_two_seconds():
    watch, _, detector, embedder, clock = _make(_gallery(("person-adult1", 3, "identify")))
    detector.faces = [_face()]
    embedder.vector = _unit(3)
    watch.step()
    assert embedder.calls == 1
    for _ in range(5):  # 1.0 s at 5 Hz: no re-embed
        clock.t += 0.2
        watch.step()
    assert embedder.calls == 1
    clock.t += 1.1  # past the 2 s mark
    watch.step()
    assert embedder.calls == 2


def test_track_continuity_holds_through_a_small_move_and_new_face_is_a_new_track():
    watch, _, detector, embedder, clock = _make(_gallery(("person-adult1", 3, "identify")))
    detector.faces = [_face(100, 80)]
    embedder.vector = _unit(3)
    watch.step()
    clock.t += 0.2
    detector.faces = [_face(106, 82)]  # same face, moved a little
    watch.step()
    assert embedder.calls == 1
    clock.t += 0.2
    detector.faces = [_face(106, 82), _face(220, 90)]  # a second person arrives
    watch.step()
    assert embedder.calls == 2
    assert watch.current().present == 2


def test_a_track_is_dropped_after_the_loss_grace():
    watch, _, detector, _, clock = _make(level="presence")
    detector.faces = [_face()]
    watch.step()
    detector.faces = []
    clock.t += 0.5
    watch.step()
    assert watch.current().present == 1  # inside the grace
    clock.t += 0.8
    watch.step()
    assert watch.current().present == 0


def test_lowering_the_level_clears_ids_at_once_and_off_clears_presence():
    watch, camera, detector, embedder, clock = _make(_gallery(("person-adult1", 3, "identify")))
    detector.faces = [_face()]
    embedder.vector = _unit(3)
    watch.step()
    assert watch.current().verdict.person_id == "person-adult1"  # type: ignore[union-attr]
    watch.set_device_level("presence")
    assert watch.current().verdict.person_id is None  # type: ignore[union-attr]
    watch.set_device_level("off")
    assert watch.current().present == 0 and watch.current().verdict is None
    reads = camera.reads
    clock.t += 0.2
    watch.step()
    assert camera.reads == reads


def test_revocation_removes_matching_within_one_sync():
    gallery = _gallery(("person-adult1", 3, "identify"))
    watch, _, detector, embedder, clock = _make(gallery)
    detector.faces = [_face()]
    embedder.vector = _unit(3)
    watch.step()
    assert watch.current().verdict.person_id == "person-adult1"  # type: ignore[union-attr]
    gallery.replace_all([])  # the next sync no longer holds the print
    clock.t += 0.2  # less than the 2 s re-embed interval
    watch.step()
    assert watch.current().verdict.person_id is None  # type: ignore[union-attr]


def test_no_embedding_or_frame_is_kept_on_the_watch_or_its_tracks():
    watch, _, detector, embedder, _ = _make()
    detector.faces = [_face()]
    embedder.vector = _unit(9)
    watch.step()
    for obj in (watch, *watch._tracks):  # noqa: SLF001
        for value in vars(obj).values():
            assert not isinstance(value, np.ndarray), vars(obj)


def test_a_verdict_goes_stale_when_nothing_refreshes_it():
    watch, _, detector, embedder, clock = _make(
        _gallery(("person-adult1", 3, "identify")), verdict_stale_after_s=10.0
    )
    detector.faces = [_face()]
    embedder.vector = _unit(3)
    watch.step()
    clock.t += 11.0
    assert watch.current().verdict is None


def test_the_rate_drops_to_two_hz_at_seventy_degrees():
    temperature = [60.0]
    watch, *_ = _make(temperature=lambda: temperature[0])
    assert watch.interval_s() == 0.2
    temperature[0] = 70.0
    assert watch.interval_s() == 0.5
    temperature[0] = None  # type: ignore[call-overload]
    assert watch.interval_s() == 0.2


def test_camera_failure_leaves_the_watch_alive():
    watch, camera, detector, _, clock = _make(level="presence")

    def boom():
        raise RuntimeError("camera gone")

    camera.get_frame = boom  # type: ignore[method-assign]
    watch.step()  # must not raise
    camera.get_frame = lambda: np.zeros((480, 640, 3), dtype=np.uint8)  # type: ignore[method-assign]
    detector.faces = [_face()]
    clock.t += 0.2
    watch.step()
    assert watch.current().present == 1


def test_read_cpu_temp_returns_none_when_unreadable(tmp_path):
    assert read_cpu_temp_c(tmp_path / "missing") is None
    zone = tmp_path / "temp"
    zone.write_text("71250\n")
    assert read_cpu_temp_c(zone) == 71.25
