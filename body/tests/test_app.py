"""Unit tests for MaiPaiBody's run loop, against the fake and a plain Event.

No daemon needed: `MaiPaiBody._run_with_head` is exercised directly with
`build_fake_body().head`, per RM-03's "without the daemon" acceptance line.
"""

from __future__ import annotations

import logging
import threading
import time

from maipai_body.app import MaiPaiBody
from maipai_body.bodies.reachy_mini.fake import build_fake_body


def test_run_holds_neutral_then_exits_within_one_second_of_stop(caplog):
    caplog.set_level(logging.INFO, logger="maipai_body.app")
    body = build_fake_body()
    stop_event = threading.Event()

    thread = threading.Thread(target=MaiPaiBody._run_with_head, args=(body.head, stop_event))
    thread.start()
    time.sleep(0.1)

    assert body.state.last_goto is not None
    assert body.state.last_goto["pose"].pitch == 0.0
    assert body.state.last_goto["antennas"] == (0.0, 0.0)
    assert body.state.held is True

    t0 = time.monotonic()
    stop_event.set()
    thread.join(timeout=2.0)
    elapsed = time.monotonic() - t0

    assert not thread.is_alive()
    assert elapsed < 1.0

    state_lines = [r.message for r in caplog.records if r.name == "maipai_body.app"]
    assert state_lines == [
        "state: starting",
        "state: holding_neutral",
        "state: stopping",
        "state: stopped",
    ]


def test_run_exits_cleanly_on_body_lost(caplog):
    caplog.set_level(logging.INFO, logger="maipai_body.app")
    body = build_fake_body()
    stop_event = threading.Event()

    thread = threading.Thread(target=MaiPaiBody._run_with_head, args=(body.head, stop_event))
    thread.start()
    time.sleep(0.1)

    body.simulate_connection_loss()
    # The loop only re-affirms the hold (and so only notices the loss)
    # every `_HOLD_REFRESH_S`; give it comfortably longer than that.
    thread.join(timeout=4.0)

    assert not thread.is_alive()
    state_lines = [
        r.message
        for r in caplog.records
        if r.name == "maipai_body.app" and r.levelno == logging.INFO
    ]
    assert state_lines == [
        "state: starting",
        "state: holding_neutral",
        "state: body_lost",
        "state: stopped",
    ]
    assert any("body lost" in r.message for r in caplog.records)
