"""Shared fixtures: the deterministic suite runs on the fake always, and on
the live simulator only when MAIPAI_BODY_LIVE=1 and a daemon answers on
localhost:8000 (otherwise skipped with a reason, never failed).
"""

from __future__ import annotations

import os
import socket

import pytest

from maipai_body.bodies.reachy_mini.fake import build_fake_body


def _daemon_reachable(host: str = "localhost", port: int = 8000, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _live_skip_reason() -> str | None:
    if os.environ.get("MAIPAI_BODY_LIVE") != "1":
        return "MAIPAI_BODY_LIVE is not set to 1"
    if not _daemon_reachable():
        return "no reachy-mini-daemon answering on localhost:8000"
    return None


LIVE_SKIP_REASON = _live_skip_reason()


def _build_live_body():
    from maipai_body.bodies.reachy_mini.client import build_live_body

    return build_live_body()


@pytest.fixture(
    params=[
        "fake",
        pytest.param(
            "live",
            marks=pytest.mark.skipif(LIVE_SKIP_REASON is not None, reason=LIVE_SKIP_REASON or ""),
        ),
    ]
)
def body(request):
    """A body wired to the seam: the fake on every run, the live simulator when reachable."""
    if request.param == "fake":
        b = build_fake_body()
    else:
        b = _build_live_body()
    yield b
    b.close()
