"""The app scaffold: hold neutral, log state changes, stop within a second."""

from __future__ import annotations

import signal
import threading
import time

from maipai_body.app import _sigint_handler, run_body
from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient


def test_run_body_holds_neutral_then_honors_stop_event(caplog):
    client = FakeReachyMiniClient()
    stop_event = threading.Event()

    with caplog.at_level("INFO", logger="maipai_body.app"):
        thread = threading.Thread(target=run_body, args=(client, stop_event))
        thread.start()
        time.sleep(0.3)  # let it reach the neutral hold
        stop_event.set()
        thread.join(timeout=2.0)

    assert not thread.is_alive(), "run_body did not stop within its join timeout"

    kinds = [command.kind for command in client.sent_commands]
    assert kinds[:2] == ["goto", "hold"], "the run loop did not go neutral then hold"

    messages = [record.getMessage() for record in caplog.records]
    assert "state: starting" in messages
    assert "state: holding_neutral" in messages
    assert "state: stopped" in messages


def test_run_body_stops_within_one_second_of_the_stop_event():
    client = FakeReachyMiniClient()
    stop_event = threading.Event()

    thread = threading.Thread(target=run_body, args=(client, stop_event))
    thread.start()
    time.sleep(0.3)

    started = time.monotonic()
    stop_event.set()
    thread.join(timeout=2.0)
    elapsed = time.monotonic() - started

    assert not thread.is_alive()
    assert elapsed < 1.0, f"run_body took {elapsed:.2f}s to stop after stop_event was set"


def test_run_body_survives_a_lost_connection(caplog):
    client = FakeReachyMiniClient()
    client.simulate_disconnect()
    stop_event = threading.Event()

    with caplog.at_level("INFO", logger="maipai_body.app"):
        run_body(client, stop_event)  # a lost connection returns immediately, never blocks

    messages = [record.getMessage() for record in caplog.records]
    assert "state: body_lost" in messages
    assert "state: stopped" in messages


def test_sigint_handler_sets_the_stop_event():
    stop_event = threading.Event()
    handler = _sigint_handler(stop_event)

    handler(signal.SIGINT, None)

    assert stop_event.is_set()
