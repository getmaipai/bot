import logging

import numpy as np
import pytest

from maipai_body.bodies.stackchan.vision_post import (
    MAX_FRAME_BYTES,
    VisionPoster,
    light_bucket,
    mean_luma,
)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self.body = body or {}

    def json(self):
        return self.body


class Session:
    def __init__(self, response=None, error=None):
        self.response = response or Response(200)
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def make(response=None, error=None):
    clock = Clock()
    session = Session(response, error)
    poster = VisionPoster(
        lambda: ("cookie-value", "https://home.test"), session=session, clock=clock
    )
    return poster, session, clock


def test_post_request_shape_and_query_filters():
    poster, session, _ = make()
    assert poster.post(b"jpeg", purpose="scene", people=22, light="dim").reason == "ok"
    url, request = session.calls[0]
    assert url == "https://home.test/api/devices/me/vision"
    assert request["headers"] == {"Cookie": "session=cookie-value", "Content-Type": "image/jpeg"}
    assert request["params"] == {"purpose": "scene", "people": 20, "light": "dim"}
    assert request["data"] == b"jpeg"
    poster.set_mode("on_demand")
    assert poster.post(b"x", purpose="ask", light="invalid").ok
    assert session.calls[1][1]["params"] == {"purpose": "ask"}


@pytest.mark.parametrize("value", [None, "bad", 3])
def test_unknown_mode_defaults_to_continual(value):
    poster, _, _ = make()
    poster.set_mode(value)
    assert poster.mode == "continual"


@pytest.mark.parametrize("mode", ["on_demand", "none"])
def test_scene_mode_gate(mode):
    poster, session, _ = make()
    poster.set_mode(mode)
    assert poster.post(b"x", purpose="scene").reason == "mode"
    assert not session.calls


def test_ask_mode_gates():
    poster, session, _ = make()
    poster.set_mode("on_demand")
    assert poster.ask_possible()
    assert poster.post(b"x", purpose="ask").ok
    poster.set_mode("none")
    assert not poster.ask_possible()
    assert poster.post(b"x", purpose="ask").reason == "mode"
    assert len(session.calls) == 1


def test_vision_off_latches_until_mode_set():
    poster, session, _ = make(Response(403, {"code": "vision_off"}))
    assert poster.post(b"x", purpose="ask").reason == "vision_off"
    assert not poster.ask_possible()
    assert poster.post(b"x", purpose="scene").reason == "vision_off"
    assert len(session.calls) == 1
    poster.set_mode("continual")
    assert poster.ask_possible()


def test_on_demand_response_changes_mode():
    poster, _, _ = make(Response(403, {"code": "vision_on_demand"}))
    result = poster.post(b"x", purpose="scene")
    assert result.reason == "vision_on_demand"
    assert poster.mode == "on_demand"


@pytest.mark.parametrize(
    ("status", "reason", "delay"), [(429, "too_fast", 10), (503, "no_vision", 60)]
)
def test_backoffs_apply_to_scene_due_but_not_asks(status, reason, delay):
    poster, _, clock = make(Response(status))
    assert poster.post(b"x", purpose="scene").reason == reason
    assert not poster.scene_due()
    clock.now += delay
    assert poster.scene_due()


def test_scene_gap_changed_and_refresh_rules():
    poster, _, clock = make()
    assert poster.scene_due()
    assert poster.post(b"x", purpose="scene").ok
    assert not poster.scene_due()
    assert not poster.scene_due(bucket_changed=True)  # Home's floor: not within 10 s
    clock.now = 10
    assert poster.scene_due(bucket_changed=True)  # a new brightness bucket goes at once
    assert not poster.scene_due()  # unchanged scenes wait for the minute
    assert poster.post(b"x", purpose="scene").ok
    clock.now = 70
    assert poster.scene_due(differs=True)
    assert not poster.scene_due(differs=False)  # a barely different picture is skipped
    clock.now = 10 + 300
    assert poster.scene_due(differs=False)  # but never longer than five minutes


def test_too_big_and_network_error():
    poster, session, _ = make()
    assert poster.post(b"x" * (MAX_FRAME_BYTES + 1), purpose="ask").reason == "too_big"
    assert not session.calls
    poster, _, _ = make(error=OSError("offline"))
    assert poster.post(b"x", purpose="ask").reason == "error"


def test_logs_only_counts_and_codes(caplog):
    secret = b"secret-image-bytes"
    poster, _, _ = make(Response(503, {"description": "secret description"}))
    with caplog.at_level(logging.INFO):
        poster.post(secret, purpose="ask")
    assert "secret-image-bytes" not in caplog.text
    assert "secret description" not in caplog.text


@pytest.mark.parametrize(
    ("luma", "lux", "expected"),
    [
        (34.9, 20, "dark"),
        (35, None, "dim"),
        (84.9, None, "dim"),
        (85, None, "bright"),
        (None, 1.49, "dark"),
        (None, 1.5, "dim"),
        (None, 4.99, "dim"),
        (None, 5.0, "bright"),
        (None, None, None),
    ],
)
def test_light_bucket(luma, lux, expected):
    assert light_bucket(luma, lux) == expected


def test_mean_luma_strided_bgr():
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    frame[::4, ::4] = (100, 100, 100)
    frame[1::4, 1::4] = (255, 255, 255)
    assert mean_luma(frame) == pytest.approx(100)


def test_the_looks_flow_from_the_bridge_to_a_scene_post_and_an_ask_post():
    """The behavior posts one picture for the scene and one for a question, then forgets them."""
    import threading
    import time

    from maipai_body.app import StackChanBehavior
    from maipai_body.bodies.stackchan.vision_post import VisionPoster

    posts = []

    class Resp:
        status_code = 200

        def json(self):
            return {"ok": True, "expires_in_s": 90}

    class Session:
        def post(self, url, params, data, headers, timeout):
            posts.append((params, len(data), timeout))
            return Resp()

    class Bridge:
        def __init__(self):
            self.look = (b"\xff\xd8jpeg\xff\xd9", 1, 120.0, None)

        def latest_look(self, *, max_age_s, take=False):
            look = self.look
            if take:
                self.look = None
            return look

    behavior = object.__new__(StackChanBehavior)
    behavior.vision_poster = VisionPoster(lambda: ("cookie", "http://hub"), session=Session())
    behavior._vision = Bridge()
    behavior._vision_posting = False
    behavior._vision_last = None
    behavior._active = threading.Event()
    behavior.night_active = lambda: False
    behavior.watch_level = lambda: "presence"
    behavior._warn_limited = lambda *a, **k: None

    behavior.post_scene(time.monotonic())
    deadline = time.monotonic() + 2
    while not posts and time.monotonic() < deadline:
        time.sleep(0.01)
    assert posts[0][0] == {"purpose": "scene", "people": 1, "light": "bright"}
    assert behavior._vision.look is None  # the frame is dropped once posted

    behavior._vision.look = (b"\xff\xd8jpeg\xff\xd9", 0, 20.0, None)
    assert behavior.vision_ask("light") is True
    assert posts[1][0] == {"purpose": "ask", "people": 0, "light": "dark"}
    assert posts[1][2] == 5.0
    assert behavior.vision_ask("light") is False  # nothing left to send


def test_refusals_double_the_interval_and_a_success_resets_it():
    poster, session, clock = make(Response(200))
    assert poster.post(b"x", purpose="scene").ok  # at 0
    session.response = Response(503, {"code": "no_vision"})
    clock.now = 70
    assert poster.post(b"x", purpose="scene").reason == "no_vision"  # back-off until 130, scale 2
    clock.now = 125
    assert not poster.scene_due()
    clock.now = 131
    assert poster.scene_due()
    session.response = Response(200)
    assert poster.post(b"x", purpose="scene").ok  # scale back to 1
    clock.now = 131 + 30
    assert not poster.scene_due()
    clock.now = 131 + 61
    assert poster.scene_due()


def test_thumbnails_tell_a_changed_scene_from_noise():
    from maipai_body.bodies.stackchan.vision_post import differs, thumbnail

    a = thumbnail(np.full((240, 320, 3), 100, dtype=np.uint8))
    assert a.shape == (12, 16)
    assert not differs(a, thumbnail(np.full((240, 320, 3), 103, dtype=np.uint8)))
    assert differs(a, thumbnail(np.full((240, 320, 3), 140, dtype=np.uint8)))
    assert differs(None, a)
