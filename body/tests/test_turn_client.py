"""G6 (receive side)'s own acceptance: a real local HTTP server
streaming real newline-delimited JSON, so the parsing and the cue
mapping are exercised against real bytes on a real socket, not a
mocked response object."""

from __future__ import annotations

import http.server
import json
import threading

import pytest

from maipai_body.expression.cue import Phase
from maipai_body.speech.turn_client import TurnAuthFailed, TurnClient, TurnLinkLost


class _NdjsonTurnServer(http.server.BaseHTTPRequestHandler):
    """Streams the class-level `lines` script as NDJSON, one line at a
    time. Records the request body and the Cookie header it received."""

    lines: list[dict] = []
    request_body: dict | None = None
    cookie_header: str | None = None
    close_early: bool = False

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        length = int(self.headers.get("Content-Length", 0))
        type(self).request_body = json.loads(self.rfile.read(length) or b"{}")
        type(self).cookie_header = self.headers.get("Cookie")

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for line in self.lines:
            self.wfile.write((json.dumps(line) + "\n").encode("utf-8"))
            self.wfile.flush()
        if self.close_early:
            self.close_connection = True


@pytest.fixture
def ndjson_server():
    def _reset(lines: list[dict], *, close_early: bool = False):
        _NdjsonTurnServer.lines = lines
        _NdjsonTurnServer.request_body = None
        _NdjsonTurnServer.cookie_header = None
        _NdjsonTurnServer.close_early = close_early

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _NdjsonTurnServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, _NdjsonTurnServer, _reset
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _base_url(server) -> str:
    return f"http://127.0.0.1:{server.server_port}"


def test_signal_then_done_yields_signal_and_done_cues_in_order(ndjson_server):
    server, handler, reset = ndjson_server
    reset(
        [
            {"type": "turn_meta", "conversation_id": "conv-1", "turn_id": "turn-1"},
            {
                "type": "signal",
                "signal": {
                    "primary_act": "inform",
                    "expressed_emotion": "happiness",
                    "emotion_intensity": "moderate",
                },
            },
            {"type": "delta", "text": "Hello "},
            {"type": "delta", "text": "there!"},
            {"type": "done", "value": {}},
        ]
    )
    client = TurnClient(_base_url(server), "cookie-abc")

    events = list(client.stream("hey maipai"))

    phases = [e.cue.phase for e in events if e.cue]
    assert phases == [Phase.SIGNAL, Phase.DONE]
    assert events[0].cue.primary_act == "inform"
    assert events[0].cue.expressed_emotion == "happiness"
    assert events[0].cue.emotion_intensity == "moderate"
    assert events[-1].reply_text == "Hello there!"
    assert events[-1].conversation_id == "conv-1"
    assert events[-1].turn_id == "turn-1"


def test_an_error_event_yields_a_cancel_cue(ndjson_server):
    server, handler, reset = ndjson_server
    reset(
        [
            {"type": "turn_meta", "conversation_id": "conv-1", "turn_id": "turn-1"},
            {"type": "error", "error": "cancelled", "code": "turn_cancelled"},
        ]
    )
    client = TurnClient(_base_url(server), "cookie-abc")

    events = list(client.stream("hey maipai"))

    assert len(events) == 1
    assert events[0].cue.phase == Phase.CANCEL


def test_a_generic_error_also_yields_a_cancel_cue(ndjson_server):
    """No error-code-specific cue exists at the floor - every error
    kind stops the presentation the same way."""
    server, handler, reset = ndjson_server
    reset([{"type": "error", "error": "the model timed out"}])
    client = TurnClient(_base_url(server), "cookie-abc")

    events = list(client.stream("hey maipai"))

    assert len(events) == 1
    assert events[0].cue.phase == Phase.CANCEL


def test_status_reasoning_and_spoken_cue_events_are_ignored(ndjson_server):
    """No cue mapping exists for these at the floor (EXPR-03's own
    future job) - they must not raise, and must not produce an event."""
    server, handler, reset = ndjson_server
    reset(
        [
            {"type": "status", "text": "thinking", "stage": "thinking"},
            {"type": "reasoning", "text": "let me think..."},
            {"type": "spoken_cue", "text": "let me check that"},
            {"type": "done", "value": {}},
        ]
    )
    client = TurnClient(_base_url(server), "cookie-abc")

    events = list(client.stream("hey maipai"))

    assert len(events) == 1
    assert events[0].cue.phase == Phase.DONE


def test_the_request_body_carries_the_robot_surface_and_the_text(ndjson_server):
    server, handler, reset = ndjson_server
    reset([{"type": "done", "value": {}}])
    client = TurnClient(_base_url(server), "cookie-abc")

    list(client.stream("what time is it"))

    assert handler.request_body["surface"] == "robot"
    assert handler.request_body["text"] == "what time is it"
    assert handler.request_body["spoken"] is True
    assert handler.request_body["speaker_evidence"] is None
    assert handler.request_body["present"] is None


def test_the_session_cookie_is_sent_as_a_header(ndjson_server):
    server, handler, reset = ndjson_server
    reset([{"type": "done", "value": {}}])
    client = TurnClient(_base_url(server), "my-cookie-value")

    list(client.stream("hi"))

    assert handler.cookie_header == "session=my-cookie-value"


def test_a_malformed_line_is_skipped_not_fatal(ndjson_server):
    server, handler, reset = ndjson_server
    handler.lines = []  # write the raw script by hand below instead

    class _MalformedServer(_NdjsonTurnServer):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            self.wfile.write(b"not valid json at all\n")
            self.wfile.write((json.dumps({"type": "done", "value": {}}) + "\n").encode("utf-8"))

    server2 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MalformedServer)
    thread = threading.Thread(target=server2.serve_forever, daemon=True)
    thread.start()
    try:
        client = TurnClient(_base_url(server2), "cookie-abc")
        events = list(client.stream("hi"))
        assert len(events) == 1
        assert events[0].cue.phase == Phase.DONE
    finally:
        server2.shutdown()
        thread.join(timeout=2)


def test_a_connection_failure_raises_turn_link_lost():
    client = TurnClient("http://127.0.0.1:1", "cookie-abc")  # nothing listens here

    with pytest.raises(TurnLinkLost):
        list(client.stream("hi"))


def test_a_401_raises_turn_auth_failed_not_turn_link_lost(ndjson_server):
    """The review-caught bug: a stale/rejected session cookie was
    indistinguishable from a dropped connection, so a caller couldn't
    tell 'reconnect' from 'go re-redeem through HubLinkClient'."""

    class _UnauthorizedServer(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            body = json.dumps({"error": "Unknown or expired session"}).encode("utf-8")
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002 - stdlib signature
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _UnauthorizedServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = TurnClient(_base_url(server), "a-stale-cookie")
        with pytest.raises(TurnAuthFailed):
            list(client.stream("hi"))
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_empty_session_cookie_raises_immediately():
    with pytest.raises(ValueError, match="session_cookie"):
        TurnClient("http://127.0.0.1:1", "")
