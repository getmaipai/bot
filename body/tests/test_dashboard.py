"""EXPR-05: the dashboard's HTTP and event-stream behaviour against the fake, no browser."""

from __future__ import annotations

import http.client
import json
import time
from collections.abc import Iterator

import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.dashboard import DashboardServer
from maipai_body.expression.primitives import PRIMITIVE_NAMES
from maipai_body.hal.seam import DirectionOfArrival


class _DoaFake(FakeReachyMiniClient):
    """The recorded fixture carries no direction of arrival, so a test supplies one itself."""

    def state_feed(self, frequency: float = 10.0):
        feed = super().state_feed(frequency)

        class _WithDoa:
            def __iter__(self):
                for frame in feed:
                    yield frame.model_copy(
                        update={"doa": DirectionOfArrival(angle_rad=0.7, speech_detected=True)}
                    )

            def close(self):
                feed.close()

        return _WithDoa()

    def get_doa(self):
        return DirectionOfArrival(angle_rad=0.7, speech_detected=True)


@pytest.fixture
def served() -> Iterator[tuple[DashboardServer, FakeReachyMiniClient]]:
    client = FakeReachyMiniClient(REACHY_MINI_PROFILE)
    server = DashboardServer(client, REACHY_MINI_PROFILE, port=0, state_hz=50.0)
    server.start()
    try:
        yield server, client
    finally:
        server.stop()


def _request(
    server: DashboardServer,
    method: str,
    path: str,
    body: object | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection(server.host, server.port, timeout=5)
    sent = dict(headers or {})
    payload = None
    if body is not None:
        payload = json.dumps(body).encode()
        sent.setdefault("Content-Type", "application/json")
    connection.request(method, path, body=payload, headers=sent)
    response = connection.getresponse()
    data = response.read()
    result = (response.status, {k.lower(): v for k, v in response.getheaders()}, data)
    connection.close()
    return result


def _wait_for_state(server: DashboardServer) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        _, _, data = _request(server, "GET", "/api/state")
        state = json.loads(data)
        if state["seq"] is not None:
            return state
        time.sleep(0.02)
    raise AssertionError("the state pump never produced a frame")


def test_the_page_and_its_assets_are_served(served):
    server, _ = served
    status, headers, body = _request(server, "GET", "/")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert b"dashboard.js" in body and b"dashboard.css" in body
    assert _request(server, "GET", "/static/dashboard.js")[0] == 200
    assert _request(server, "GET", "/static/dashboard.css")[0] == 200


def test_the_dashboard_never_serves_the_link_pages_index_or_anything_outside_its_assets(served):
    server, _ = served
    assert _request(server, "GET", "/static/index.html")[0] == 404
    assert _request(server, "GET", "/static/../app.py")[0] == 404
    assert _request(server, "GET", "/static/%2e%2e/app.py")[0] == 404


def test_the_primitive_list_is_the_engines_own_vocabulary_plus_the_mute_state(served):
    server, _ = served
    status, _, data = _request(server, "GET", "/api/primitives")
    assert status == 200
    listing = json.loads(data)
    assert tuple(listing["primitives"]) == PRIMITIVE_NAMES
    assert listing["body"] == REACHY_MINI_PROFILE.id


def test_state_carries_pose_antennas_yaw_doa_and_funnel_state(served):
    server, _ = served
    state = _wait_for_state(server)
    assert state["connected"] is True
    assert set(state["head_pose"]) == {"x", "y", "z", "roll", "pitch", "yaw"}
    assert set(state["antennas"]) == {"left", "right"}
    assert isinstance(state["body_yaw"], float)
    assert state["doa"] is None  # the recorded fixture has no direction of arrival
    assert set(state["presence"]) >= {"face_detected", "speech_detected", "tip_detected"}
    assert state["arbitration"]["priority"] in {"EXPRESSION", "TRACKING", "IDLE"}
    assert state["muted"] is False


@pytest.mark.parametrize("primitive", PRIMITIVE_NAMES)
def test_every_primitive_button_renders_through_the_engine(served, primitive):
    server, client = served
    before = len(client.sent_commands)
    status, _, data = _request(server, "POST", f"/api/primitive/{primitive}", {})
    assert status == 200
    outcome = json.loads(data)
    assert outcome["rendered"] is True
    assert outcome["primitive"] == primitive
    assert len(client.sent_commands) > before


def test_state_carries_the_direction_of_arrival_when_the_body_reports_one():
    client = _DoaFake(REACHY_MINI_PROFILE)
    server = DashboardServer(client, REACHY_MINI_PROFILE, port=0, state_hz=50.0)
    server.start()
    try:
        state = _wait_for_state(server)
        assert state["doa"] == {"angle_rad": 0.7, "speech_detected": True}
        assert state["presence"]["doa_angle_rad"] == 0.7
        assert state["presence"]["speech_detected"] is True
    finally:
        server.stop()


def test_a_posted_direction_reaches_the_renderer(served):
    server, client = served
    _request(server, "POST", "/api/primitive/glance", {"direction_rad": -0.4})
    _request(server, "POST", "/api/primitive/glance", {"direction_rad": 0.4})
    yaws = [c.pose.yaw for c in client.sent_commands if c.kind == "goto" and c.pose is not None]
    assert min(yaws) < 0 < max(yaws)


def test_an_unknown_primitive_is_a_404_and_sends_nothing(served):
    server, client = served
    status, _, _ = _request(server, "POST", "/api/primitive/moonwalk", {})
    assert status == 404
    assert client.sent_commands == []


def test_a_bad_direction_is_a_400_and_sends_nothing(served):
    server, client = served
    status, _, _ = _request(server, "POST", "/api/primitive/glance", {"direction_rad": "left"})
    assert status == 400
    assert client.sent_commands == []


def test_mute_suppresses_listen_and_unmute_settles(served):
    server, client = served
    status, _, data = _request(server, "POST", "/api/muted", {"muted": True})
    assert status == 200 and json.loads(data)["rendered_primitive"] == "muted"
    assert _wait_for_state(server)["muted"] is True
    _, _, data = _request(server, "POST", "/api/primitive/listen", {})
    outcome = json.loads(data)
    assert outcome["rendered"] is False and outcome["suppressed_reason"] == "muted"
    status, _, data = _request(server, "POST", "/api/muted", {"muted": False})
    assert json.loads(data)["rendered_primitive"] == "settle"
    assert _wait_for_state(server)["muted"] is False


def test_stop_is_never_suppressed_even_while_muted(served):
    server, client = served
    _request(server, "POST", "/api/muted", {"muted": True})
    _, _, data = _request(server, "POST", "/api/primitive/stop", {})
    assert json.loads(data)["rendered"] is True
    assert client.sent_commands[-1].kind == "hold"


def test_a_lost_body_is_a_503_and_the_state_says_disconnected(served):
    server, client = served
    client.simulate_disconnect()
    status, _, data = _request(server, "POST", "/api/primitive/nod", {})
    assert status == 503
    assert "lost" in json.loads(data)["error"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = json.loads(_request(server, "GET", "/api/state")[2])
        if state["connected"] is False:
            return
        time.sleep(0.02)
    raise AssertionError("the state never reported the body as disconnected")


def test_a_cross_origin_page_cannot_drive_the_body(served):
    server, client = served
    origin = {"Origin": "http://example.com"}
    assert _request(server, "POST", "/api/primitive/nod", {}, origin)[0] == 403
    assert _request(server, "POST", "/api/muted", {"muted": True}, origin)[0] == 403
    rebound = {"Host": "example.com"}
    assert _request(server, "POST", "/api/primitive/nod", {}, rebound)[0] == 403
    assert client.sent_commands == []


def test_a_post_that_is_not_json_is_refused(served):
    server, client = served
    status, _, _ = _request(
        server, "POST", "/api/primitive/nod", None, {"Content-Type": "text/plain"}
    )
    assert status == 415
    assert client.sent_commands == []


def test_the_event_stream_pushes_state_snapshots(served):
    server, _ = served
    connection = http.client.HTTPConnection(server.host, server.port, timeout=5)
    connection.request("GET", "/events")
    response = connection.getresponse()
    assert response.status == 200
    assert response.getheader("Content-Type").startswith("text/event-stream")
    snapshots = []
    while len(snapshots) < 3:
        line = response.readline().decode()
        if line.startswith("data: "):
            snapshots.append(json.loads(line[len("data: ") :]))
    connection.close()
    assert all("head_pose" in s and "arbitration" in s for s in snapshots)


def test_stopping_the_server_ends_open_event_streams(served):
    server, _ = served
    connection = http.client.HTTPConnection(server.host, server.port, timeout=5)
    connection.request("GET", "/events")
    response = connection.getresponse()
    response.readline()
    server.stop()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if response.readline() == b"":
            connection.close()
            return
    raise AssertionError("the stream outlived the server")
