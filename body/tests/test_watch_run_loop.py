"""FACE-WATCH-01: the run loop's hook for the vision watch."""

from __future__ import annotations

import threading
import time

from maipai_body.vision.gallery import FaceVerdict
from maipai_body.vision.watch import WatchSnapshot
from tests.test_run_loop import _make_loop


class _StubWatch:
    def __init__(self, verdict: FaceVerdict | None) -> None:
        self.verdict = verdict
        self.level = "identify"
        self.ran = threading.Event()

    @property
    def device_level(self):
        return self.level

    def set_device_level(self, level) -> None:
        self.level = level

    def current(self) -> WatchSnapshot:
        return WatchSnapshot(self.level, 1, self.verdict)  # type: ignore[arg-type]

    def run(self, stop_event: threading.Event) -> None:
        self.ran.set()
        stop_event.wait()


def test_watch_verdict_feeds_the_turn_and_the_old_presence_trigger_is_off():
    from maipai_body.hal.seam import FaceTrackTarget

    verdict = FaceVerdict(person_id="person-abc123", level="tentative", score=0.9)
    loop, parts = _make_loop(vision_watch=_StubWatch(verdict))
    assert loop._current_face_verdict() == verdict  # noqa: SLF001
    parts["client"].face_target = FaceTrackTarget(detected=True)
    calls: list[int] = []
    loop._maybe_check_face = lambda *_: calls.append(1)  # type: ignore[method-assign]
    loop._presence_tick(threading.Event())  # noqa: SLF001
    assert calls == []  # the daemon tracker no longer triggers recognition


def test_snapshot_reports_the_watch_level_only_when_a_watch_is_attached():
    plain, _ = _make_loop()
    assert "watch_level" not in plain.snapshot()
    watch = _StubWatch(None)
    loop, _ = _make_loop(vision_watch=watch)
    assert loop.snapshot()["watch_level"] == "identify"


def test_set_watch_level_reaches_the_watch_and_pings_the_state_reporter():
    changes: list[int] = []
    watch = _StubWatch(None)
    loop, _ = _make_loop(vision_watch=watch, on_change=lambda: changes.append(1))
    loop.set_watch_level("presence")
    assert watch.level == "presence" and loop.snapshot()["watch_level"] == "presence"
    assert changes == [1]


def test_run_starts_the_watch_thread():
    watch = _StubWatch(None)
    loop, _ = _make_loop(vision_watch=watch)
    stop = threading.Event()
    thread = threading.Thread(target=loop.run, args=(stop,), daemon=True)
    thread.start()
    try:
        assert watch.ran.wait(2.0)
    finally:
        stop.set()
        thread.join(5.0)
        time.sleep(0)
