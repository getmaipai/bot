"""SCENE-WIRE-BOT: the landed scene pieces run inside the real loop.

SCENE-01g boxes reach `present`, MOVE-SCENE-05 runs one face search off the loop thread, and
SELF-SCENE-02 reads the battery on a worker so the tick does no I/O."""

from __future__ import annotations

import threading
import time

import numpy as np

from maipai_body.vision.gallery import FaceGallery
from maipai_body.vision.watch import VisionWatch, WatchSnapshot
from tests.test_motion_state_hold import Bench
from tests.test_move_scene_05 import Dropper
from tests.test_power_ladder import _Bench
from tests.test_run_loop import _make_loop
from tests.test_speaker_evidence_turn import _run_one, _Watch
from tests.test_watch_levels import MODEL, SHA, _Camera, _Clock, _Detector, _Embedder, _face

TORSO = (0.30, 0.25, 0.40, 0.70)
UNKNOWN_BODY = {"person": None, "basis": "unknown", "level": "unknown"}


def _boxed_watch(*, present=0, person_boxes=(), face_boxes=()):
    watch = _Watch(present)
    watch.snapshot = WatchSnapshot(
        level="on", present=present, verdict=None, person_boxes=person_boxes, face_boxes=face_boxes
    )
    return watch


# ---- SCENE-01g ---------------------------------------------------------------------------


def test_a_torso_box_with_no_face_adds_one_unknown_entry_to_the_loops_present_list():
    loop, parts = _run_one(vision_watch=_boxed_watch(person_boxes=(TORSO,)))
    assert parts["turn"].present_calls == [[UNKNOWN_BODY]]


def test_a_box_with_a_face_inside_it_is_one_person_not_two():
    face = (0.45, 0.30, 0.10, 0.12)
    watch = _boxed_watch(present=1, person_boxes=(TORSO,), face_boxes=(face,))
    loop, parts = _run_one(vision_watch=watch)
    (present,) = parts["turn"].present_calls
    assert present == [{"person": None, "basis": "face", "level": "unknown"}]


def test_the_real_watch_snapshot_carries_boxes_as_shares_and_no_image():
    clock = _Clock()
    detector = _Detector()
    detector.faces = [_face(x=96.0, y=72.0, size=64.0)]
    watch = VisionWatch(
        _Camera(),
        detector,
        _Embedder(),
        FaceGallery(model_id=MODEL, model_sha256=SHA),
        clock=clock,
        person_boxes=lambda: [TORSO],
    )
    watch.step()
    snap = watch.current()
    assert snap.person_boxes == (TORSO,)
    assert snap.face_boxes == ((0.3, 0.3, 0.2, 64.0 / 240),)
    assert all(not isinstance(v, np.ndarray) for v in vars(snap).values())
    watch.drop_tracks()
    assert watch.current().face_boxes == ()


def test_an_unreadable_person_detector_still_counts_faces():
    def broken():
        raise RuntimeError("model not loaded")

    watch = VisionWatch(
        _Camera(),
        _Detector(),
        _Embedder(),
        FaceGallery(model_id=MODEL, model_sha256=SHA),
        person_boxes=broken,
    )
    assert watch.current().person_boxes == ()


# ---- MOVE-SCENE-05 -----------------------------------------------------------------------


def _join_search(loop) -> None:
    worker = loop._face_search_thread
    if worker is not None:
        worker.join(timeout=3.0)


def test_a_set_down_runs_one_face_search_off_the_caller_and_drops_old_tracks():
    searched: list[float] = []
    threads: list[str] = []
    watch = Dropper()
    watch.current = lambda: WatchSnapshot("on", 0, None)
    watch.device_level = "on"

    def search():
        threads.append(threading.current_thread().name)
        time.sleep(1.0)  # a slow search must not hold the caller
        searched.append(time.monotonic())

    bench = Bench(face_search=search, vision_watch=watch)
    started = time.monotonic()
    bench.loop.note_set_down()
    bench.loop.note_set_down()  # a second signal while one search runs adds nothing
    assert time.monotonic() - started < 0.05
    _join_search(bench.loop)
    assert len(searched) == 1
    assert searched[0] - started <= 5.0
    assert threads == ["face-search"]
    assert watch.dropped == 2  # the tracks are dropped on every signal, the search runs once


def test_the_orientation_set_down_hook_feeds_the_loop():
    from maipai_body.bodies.stackchan.orientation import OrientationReactions

    searches: list[int] = []
    bench = Bench(face_search=lambda: searches.append(1))
    reactions = OrientationReactions(
        face=lambda _e: None,
        say=lambda _l: True,
        rotate=lambda _d: None,
        hold_motion=lambda _h: None,
        quiet=lambda: "",
        busy=lambda: False,
        on_set_down=bench.loop.note_set_down,
    )
    reactions.note_set_down()
    _join_search(bench.loop)
    assert searches == [1]


# ---- SELF-SCENE-02 -----------------------------------------------------------------------


def test_a_fake_battery_drives_the_ladder_and_the_state_frame_through_the_real_loop():
    bench = _Bench()
    bench.step(12)
    frame = bench.loop.snapshot()
    assert (frame["battery_level"], frame["charging"], frame["low_power"]) == (12, False, True)
    assert bench.dim == [True]
    bench.step(40, charging=True)
    frame = bench.loop.snapshot()
    assert (frame["battery_level"], frame["charging"], frame["low_power"]) == (40, True, False)
    assert bench.dim == [True, False]


def test_a_slow_battery_source_never_delays_the_tick():
    reads: list[int] = []

    def slow():
        reads.append(1)
        time.sleep(1.0)
        return {"percent": 50, "charging": False}

    now = [1000.0]
    loop, _ = _make_loop(battery_status=slow, sleep_clock=lambda: now[0])
    for step in range(3):
        now[0] += 6.0
        began = time.perf_counter()
        loop._power_tick(False)
        assert time.perf_counter() - began < 0.05, f"tick {step} waited on the battery"
    assert len(reads) == 1  # one read at a time, however many ticks come
    loop._battery_status.wait_idle(timeout=3.0)
    loop._power_tick(False)
    assert loop.snapshot()["battery_level"] == 50


def test_a_failing_battery_source_keeps_the_last_answer_and_never_raises():
    state = {"fail": False}

    def source():
        if state["fail"]:
            raise OSError("bus gone")
        return {"percent": 33, "charging": False}

    bench = _Bench()
    bench.loop._battery_status._read = source
    bench.step(None)
    state["fail"] = True
    bench.step(None)
    assert bench.loop.snapshot()["battery_level"] == 33


def test_no_battery_source_leaves_the_ladder_off_and_the_frame_silent():
    loop, _ = _make_loop()
    loop._power_tick(False)
    frame = loop.snapshot()
    assert not {"battery_level", "charging", "low_power"} & set(frame)
    assert loop._battery_status is None
