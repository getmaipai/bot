"""MOVES-02 on a physical unit: teach a move by hand, name it, replay it.

NEEDS THE UNIT. Usage (from ``body/``, the robot's daemon answering)::

    uv run python scripts/teach_move_live.py wave --seconds 8 --host <robot> --port 8000

The head goes limp (gravity compensation) for ``--seconds`` while a
person moves the head and antennas by hand; the recording is saved to
``--dir`` (default ``./taught-moves``) as ``<name>.json`` and replayed
once. Whether the replay matches what the hand did is judged by eye on
the unit; this script prints what it recorded (pose count, duration,
peak head yaw) and invents nothing else. Against the simulator there is
no hand, so the recording is a still pose and is refused as too short.
"""

from __future__ import annotations

import argparse
import math
import threading
from pathlib import Path

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.moves.library import load_pins
from maipai_body.moves.player import MovePlayer
from maipai_body.moves.store import MoveStore
from maipai_body.moves.teach import TeachSession
from maipai_body.presence.arbitration import ArbitrationState


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name")
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dir", type=Path, default=Path("taught-moves"))
    args = parser.parse_args()

    reserved = {name for pin in load_pins() for name in pin.files}
    store = MoveStore(args.dir, reserved=reserved)
    body = ReachyMiniClient(REACHY_MINI_PROFILE, host=args.host, port=args.port)
    arbitration = ArbitrationState(expression_active=True)
    try:
        session = TeachSession(body, store)
        print(f"The head is limp for {args.seconds:.0f} s. Move it by hand now.")
        timer = threading.Timer(args.seconds, session.stop)
        timer.start()
        move = session.teach(args.name, arbitration)
        timer.cancel()
        peak = max(abs(frame.pose.yaw) for frame in move.frames)
        print(
            f"Recorded {len(move.times)} poses over {move.duration_s:.2f} s, "
            f"peak head yaw {math.degrees(peak):.1f} deg. Replaying."
        )
        MovePlayer(body, REACHY_MINI_PROFILE).play(move, arbitration)
    finally:
        body.disconnect()


if __name__ == "__main__":
    main()
