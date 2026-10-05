"""MOVES-01 acceptance on the fake body and the simulator (not a physical unit).

Runs against the fake always and against ``reachy-mini-daemon --sim``
when ``MAIPAI_BODY_LIVE=1`` (the ``body_client`` fixture). Nothing here has
run on a physical unit; that check is separate (see docs/BACKLOG.md MOVES-01).
The move is
synthetic; the acceptance phrase is exercised end to end through
``MovesService.ask``.
"""

from __future__ import annotations

import math

from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.moves.player import MovePlayer
from maipai_body.moves.recorded_move import RecordedMove
from maipai_body.moves.service import MovesService
from maipai_body.presence.arbitration import ArbitrationState
from tests.test_moves import _matrix, _move_json  # noqa: F401  (shared synthetic move)


def test_do_the_happy_dance_plays_the_move_on_the_body(body_client):
    from maipai_body.hal.seam import HeadPose

    move = RecordedMove.from_json("happy1", _move_json(samples=11, dt=0.1, yaw_deg=15.0))
    service = MovesService(
        MovePlayer(body_client, REACHY_MINI_PROFILE), lambda name: move, ["happy1"]
    )
    assert service.ask("do the happy dance", ArbitrationState(expression_active=True)) == "happy1"
    target = HeadPose(yaw=math.radians(15.0))
    # The fake records commands, so the last one is the evidence there. On the
    # simulator this proves the daemon accepted the whole stream without
    # error; reading the state feed back is part of the unit measurement.
    sent = getattr(body_client, "sent_commands", None)
    if sent is not None:
        assert abs(sent[-1].pose.yaw - target.yaw) < 1e-6
