"""Shared fixtures: the deterministic suite runs against the fake always, and
against the live simulator only when it is reachable and asked for.
"""

from __future__ import annotations

import socket

import pytest

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE

LIVE_HOST = "localhost"
LIVE_PORT = 8000


def _live_daemon_reachable() -> bool:
    try:
        with socket.create_connection((LIVE_HOST, LIVE_PORT), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.fixture(params=["fake", "live"])
def body_client(request):
    """A body client behind the seam: the fake always, the live simulator opt-in.

    Live only runs when ``MAIPAI_BODY_LIVE=1`` is set and the daemon
    answers on port 8000; otherwise it is skipped with a reason, never
    failed (AGENTS.md: "the whole suite runs twice ... otherwise skipped
    with a reason, never failed").
    """
    if request.param == "fake":
        client = FakeReachyMiniClient(REACHY_MINI_PROFILE)
        yield client
        return

    import os

    if os.environ.get("MAIPAI_BODY_LIVE") != "1":
        pytest.skip("MAIPAI_BODY_LIVE is not set to 1")
    if not _live_daemon_reachable():
        pytest.skip(f"no daemon answering on {LIVE_HOST}:{LIVE_PORT}")

    client = ReachyMiniClient(REACHY_MINI_PROFILE, host=LIVE_HOST, port=LIVE_PORT)
    yield client
    client.disconnect()
