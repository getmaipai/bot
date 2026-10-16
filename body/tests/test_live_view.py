"""LIVE-VIEW-01 (bot half): the stream, its cyan cue and every way it stops."""

from __future__ import annotations

import time

from maipai_body.indicator import looks
from maipai_body.indicator.live import LiveCaptureTap
from maipai_body.vision.live_view import FRAME_PERIOD_S, MAX_FRAME_BYTES, LiveViewStreamer

JPEG = b"\xff\xd8\xff\xe0frame"


class _Camera:
    def __init__(self, log: list[str], frame=JPEG) -> None:
        self.log = log
        self.frame = frame

    def get_frame_jpeg(self):
        self.log.append("read")
        return self.frame


def _wait(predicate, timeout=3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class Rig:
    def __init__(self, *, refusal=None, status=204, frame=JPEG, connected=True) -> None:
        self.log: list[str] = []
        self.posts: list[tuple[str, bytes]] = []
        self.status = status
        self.reason = refusal
        self.connected = connected
        self.tap = LiveCaptureTap(_Camera(self.log, frame))
        self.tap.subscribe(lambda facts: self.log.append("cue"))

        def post(view_id, jpeg):
            self.posts.append((view_id, jpeg))
            return self.status

        self.streamer = LiveViewStreamer(
            camera=self.tap,
            post_frame=post,
            refusal=lambda: self.reason,
            connected=lambda: self.connected,
        )

    def start(self, view_id="view-1"):
        return self.streamer.start({"view_id": view_id, "fps": 5, "size": "640x360"})


def test_the_eyes_go_cyan_before_every_frame_read():
    rig = Rig()
    assert rig.start() == {"live_view": "streaming"}
    assert _wait(lambda: len(rig.posts) >= 3)
    rig.streamer.stop({"view_id": "view-1"})
    reads = [i for i, e in enumerate(rig.log) if e == "read"]
    assert len(reads) >= 3
    assert all(rig.log[i - 1] == "cue" for i in reads)
    assert all(view == "view-1" and jpeg == JPEG for view, jpeg in rig.posts)


def test_the_frame_period_keeps_the_cue_continuous():
    assert FRAME_PERIOD_S == 0.2
    assert FRAME_PERIOD_S < looks.CUE_HOLD_S


def test_a_held_robot_refuses_the_start_and_reads_nothing():
    rig = Rig(refusal="held")
    assert rig.start() == {"live_view": "refused", "reason": "held"}
    time.sleep(0.1)
    assert rig.log == [] and rig.posts == []
    assert rig.streamer.streaming is False


def test_picking_the_robot_up_mid_stream_stops_it():
    rig = Rig()
    rig.start()
    assert _wait(lambda: len(rig.posts) >= 1)
    rig.reason = "held"
    assert _wait(lambda: not rig.streamer.streaming)


def test_a_channel_drop_stops_the_stream_at_once():
    rig = Rig()
    rig.start()
    assert _wait(lambda: len(rig.posts) >= 1)
    started = time.monotonic()
    rig.streamer.on_channel_drop()
    assert rig.streamer.streaming is False
    count = len(rig.posts)
    time.sleep(0.3)
    assert len(rig.posts) == count
    assert time.monotonic() - started < 2.0


def test_a_lost_channel_seen_by_the_loop_also_stops_it():
    rig = Rig()
    rig.start()
    assert _wait(lambda: len(rig.posts) >= 1)
    rig.connected = False
    assert _wait(lambda: not rig.streamer.streaming)


def test_a_404_from_the_hub_stops_streaming():
    rig = Rig(status=404)
    rig.start()
    assert _wait(lambda: not rig.streamer.streaming)
    assert len(rig.posts) == 1


def test_repeated_post_failures_stop_streaming():
    rig = Rig(status=500)
    rig.start()
    assert _wait(lambda: not rig.streamer.streaming, timeout=5.0)
    assert len(rig.posts) == 5


def test_an_oversize_frame_is_dropped_locally():
    rig = Rig(frame=b"\xff\xd8" + b"x" * MAX_FRAME_BYTES)
    rig.start()
    time.sleep(0.5)
    rig.streamer.stop({})
    assert rig.posts == []


def test_the_ten_minute_cap_stops_the_stream():
    now = [0.0]
    log: list[str] = []
    posts: list[str] = []
    streamer = LiveViewStreamer(
        camera=_Camera(log),
        post_frame=lambda v, j: posts.append(v) or 204,
        refusal=lambda: None,
        connected=lambda: True,
        clock=lambda: now[0],
    )
    streamer.start({"view_id": "view-1"})
    assert _wait(lambda: len(posts) >= 1)
    now[0] = 601.0
    assert _wait(lambda: not streamer.streaming)


def test_stop_of_another_view_is_ignored_and_a_new_start_replaces_the_old():
    rig = Rig()
    rig.start("view-1")
    rig.streamer.stop({"view_id": "view-other"})
    assert rig.streamer.streaming is True
    rig.start("view-2")
    mark = len(rig.posts)
    assert _wait(lambda: any(v == "view-2" for v, _ in rig.posts[mark:]))
    rig.streamer.stop({"view_id": "view-2"})
    assert rig.streamer.streaming is False


def test_a_start_without_a_view_id_is_an_error():
    rig = Rig()
    try:
        rig.streamer.start({})
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_the_loop_refuses_the_camera_while_held_or_in_an_alarm():
    from tests.test_run_loop import _make_loop

    loop, _ = _make_loop()
    assert loop.live_view_refusal() is None
    with loop._lock:
        loop._state.alarm = True
    assert loop.live_view_refusal() == "alarm"
