from __future__ import annotations

import threading
import time
from unittest.mock import Mock

import requests

from maipai_body.link.state import StateReporter


class _Response:
    def __init__(self, status_code=204):
        self.status_code = status_code


def _reporter(session, snapshot, *, interval_s=15.0, stop_event=None):
    return StateReporter(
        lambda: ("cookie-value", "https://hub.example.test"),
        stop_event or threading.Event(),
        snapshot,
        threading.Event(),
        interval_s=interval_s,
        session=session,
    )


def test_successful_report_sends_frame_and_cookie_header():
    session = Mock(spec=requests.Session)
    session.put.return_value = _Response()
    frame = {"activity": "idle", "muted": False, "tracking": False}
    reporter = _reporter(session, lambda: frame)

    thread = threading.Thread(target=reporter.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 1
    while not session.put.called and time.monotonic() < deadline:
        time.sleep(0.005)
    reporter._stop_event.set()
    thread.join(timeout=0.5)

    session.put.assert_called_once_with(
        "https://hub.example.test/api/devices/me/state",
        json=frame,
        headers={"Cookie": "session=cookie-value"},
        timeout=5.0,
    )
    assert not thread.is_alive()


def test_change_event_sends_another_frame():
    session = Mock(spec=requests.Session)
    session.put.return_value = _Response()
    frame = {"activity": "idle", "muted": False, "tracking": False}
    reporter = _reporter(session, lambda: frame)
    thread = threading.Thread(target=reporter.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 1
    while session.put.call_count < 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    frame["activity"] = "listening"
    reporter._on_change.set()
    deadline = time.monotonic() + 1
    while session.put.call_count < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    reporter._stop_event.set()
    thread.join(timeout=0.5)
    assert session.put.call_count == 2
    assert session.put.call_args_list[1].kwargs["json"]["activity"] == "listening"


def test_heartbeat_sends_after_short_interval():
    session = Mock(spec=requests.Session)
    session.put.return_value = _Response()
    reporter = _reporter(session, lambda: {"activity": "idle"}, interval_s=0.03)
    thread = threading.Thread(target=reporter.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 1
    while session.put.call_count < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    reporter._stop_event.set()
    thread.join(timeout=0.5)
    assert session.put.call_count >= 2


def test_connection_failure_logs_and_waits_for_next_wake(caplog):
    session = Mock(spec=requests.Session)
    session.put.side_effect = requests.RequestException("offline")
    stop_event = threading.Event()
    reporter = _reporter(session, lambda: {"activity": "starting"}, stop_event=stop_event)
    with caplog.at_level("WARNING", logger="maipai_body.link.state"):
        thread = threading.Thread(target=reporter.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 1
        while not session.put.called and time.monotonic() < deadline:
            time.sleep(0.005)
        stop_event.set()
        thread.join(timeout=0.5)
    session.put.assert_called_once()
    assert not thread.is_alive()
    assert "robot state report failed" in caplog.text


def test_pre_set_stop_event_returns_without_sending():
    session = Mock(spec=requests.Session)
    reporter = _reporter(session, lambda: {})
    reporter._stop_event.set()
    reporter.run()
    session.put.assert_not_called()
