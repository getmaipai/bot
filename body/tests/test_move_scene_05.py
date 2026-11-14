"""MOVE-SCENE-05: after the body is handled, who is near and the light and camera are re-checked."""

from __future__ import annotations

from maipai_body.bodies.stackchan.orientation import SENSOR_SETTLE_S
from maipai_body.presence import motion_state
from tests.test_motion_state_hold import Bench
from tests.test_stackchan_orientation import Harness


class Dropper:
    def __init__(self) -> None:
        self.dropped = 0

    def drop_tracks(self) -> None:
        self.dropped += 1

    drop_heard = drop_tracks


def lift_and_put_down(bench: Bench) -> float:
    bench.tick(3.0, shake=True)
    started = bench.now
    bench.tick(motion_state.PUT_DOWN_STILL_S + 2.0)
    return started


def test_the_face_search_runs_once_within_five_seconds_of_set_down():
    searches: list[float] = []
    bench = Bench(face_search=lambda: searches.append(bench.now))
    bench.tick(3.0, shake=True)
    assert searches == []  # nothing while carried
    bench.tick(motion_state.PUT_DOWN_STILL_S + 2.0)
    assert len(searches) == 1
    put_down_at = bench.now - 2.0  # the still window ended about here
    assert searches[0] - put_down_at <= 5.0
    bench.tick(10.0)
    assert len(searches) == 1


def test_light_and_camera_are_ignored_for_thirty_seconds_after_a_carry():
    edges: list[float] = []
    bench = Bench(face_search=lambda: edges.append(bench.now))
    assert not bench.loop.sensors_settling()
    lift_and_put_down(bench)
    bench.now = edges[0] + SENSOR_SETTLE_S - 1
    assert bench.loop.sensors_settling()
    bench.now = edges[0] + SENSOR_SETTLE_S + 1
    assert not bench.loop.sensors_settling()


def test_the_sleep_policy_gets_no_luma_or_face_while_settling():
    seen: list[float | None] = []
    bench = Bench(luma_source=lambda: seen.append(0.1) or 0.1)
    bench.loop._sleep_auto = type("P", (), {"update": lambda *a, **k: seen.append(k) or None})()
    bench.loop.note_set_down()
    bench.loop._sleep_tick(
        type("O", (), {"speech_detected": False, "face_detected": True})(), False
    )
    (kwargs,) = seen
    assert kwargs["luma"] is None and kwargs["face"] is False
    bench.now += SENSOR_SETTLE_S + 1
    seen.clear()
    bench.loop._sleep_tick(
        type("O", (), {"speech_detected": False, "face_detected": True})(), False
    )
    assert seen[0] == 0.1 and seen[1]["face"] is True


def test_old_tracks_are_dropped_and_the_stale_verdict_cleared():
    watch, voice = Dropper(), Dropper()
    bench = Bench(vision_watch=watch, voice_identifier=voice)
    bench.loop._state.face_verdict = object()
    bench.loop._state.face_verdict_at = 1.0
    lift_and_put_down(bench)
    assert watch.dropped == 1 and voice.dropped == 1
    assert bench.loop._state.face_verdict is None


def test_the_stackchan_pose_back_to_upright_feeds_the_same_recheck():
    h = Harness()
    calls: list[int] = []
    h.reactions._on_set_down = lambda: calls.append(1)
    h.event("+x")
    assert calls == []
    h.now += 100
    h.event("+y")
    assert calls == [1]
    h.now += SENSOR_SETTLE_S - 1
    assert h.reactions.sensors_untrusted()


def test_the_present_list_is_rebuilt_from_fresh_tracks_only():
    from maipai_body.vision.watch import VisionWatch
    from tests.test_watch_levels import _Camera, _Clock, _Detector, _Embedder, _face, _gallery

    clock, detector = _Clock(), _Detector()
    watch = VisionWatch(_Camera(), detector, _Embedder(), _gallery(), clock=clock)
    detector.faces = [_face(100.0), _face(400.0)]
    watch.step()
    assert watch.current().present == 2
    detector.faces = []
    watch.drop_tracks()
    assert watch.current().present == 0  # the old tracks are gone, not waiting to expire
    clock.t += 1.0
    detector.faces = [_face(250.0)]
    watch.step()
    assert watch.current().present == 1  # rebuilt from what is seen now
