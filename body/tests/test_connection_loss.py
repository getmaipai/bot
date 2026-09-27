"""Losing the connection raises BodyLost once; nothing is retried silently."""

from __future__ import annotations

import pytest

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.hal.errors import BodyLost
from maipai_body.hal.seam import HeadPose


def test_losing_connection_raises_body_lost_and_refuses_further_commands(body_client):
    if isinstance(body_client, FakeReachyMiniClient):
        body_client.simulate_disconnect()
    else:
        assert isinstance(body_client, ReachyMiniClient)
        # The SDK's own graceful disconnect() stops its liveness-checking
        # thread outright, freezing its "alive" flag at True forever (verified
        # live: a command sent after disconnect() just silently no-ops,
        # never raising). A lost connection in the field looks nothing like
        # that call; it looks like the socket dying underneath a still-live
        # client, which this reproduces directly, and which the client
        # observes as websockets' own ConnectionClosed on the next command
        # (also verified live, the exception client.py's _CONNECTION_LOST_ERRORS
        # now catches).
        body_client._reachy.client._ws.close()

    with pytest.raises(BodyLost):
        body_client.enable()

    with pytest.raises(BodyLost):
        body_client.goto(pose=HeadPose(pitch=0.05), duration_s=0.1)
