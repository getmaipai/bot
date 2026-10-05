"""MOVES-02 on a physical unit. Skipped unless ``MAIPAI_BODY_UNIT=1``.

Needs the unit and a person at it. Run::

    cd body && MAIPAI_BODY_UNIT=1 MAIPAI_UNIT_HOST=<robot> \
        uv run pytest tests/test_moves_teach_unit.py -v -s

For ten seconds the head is limp: move it and the antennas by hand. The
test asserts the recording is a well-formed move inside the envelope that
replays without error. That the replay looks like what the hand did is
judged by eye and recorded in docs/BACKLOG.md; nothing is measured here.
"""

from __future__ import annotations

import os
import threading

import pytest

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.moves.player import MovePlayer
from maipai_body.moves.store import MoveStore
from maipai_body.moves.teach import TeachSession
from maipai_body.presence.arbitration import ArbitrationState

pytestmark = pytest.mark.skipif(
    os.environ.get("MAIPAI_BODY_UNIT") != "1", reason="needs the physical unit (MAIPAI_BODY_UNIT=1)"
)


def test_a_move_taught_by_hand_on_the_unit_replays(tmp_path):
    body = ReachyMiniClient(
        REACHY_MINI_PROFILE, host=os.environ.get("MAIPAI_UNIT_HOST", "localhost"), port=8000
    )
    try:
        arbitration = ArbitrationState(expression_active=True)
        session = TeachSession(body, MoveStore(tmp_path))
        timer = threading.Timer(10.0, session.stop)
        timer.start()
        print("Move the head and antennas by hand now.")
        move = session.teach("by_hand", arbitration)
        timer.cancel()
        assert len(move.times) >= 2
        MovePlayer(body, REACHY_MINI_PROFILE).play(move, arbitration)
    finally:
        body.disconnect()
