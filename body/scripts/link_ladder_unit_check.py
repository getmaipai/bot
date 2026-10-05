"""LINK-STATE-01: run the offline ladder's body cues on the real unit.

Hardware-only. It drives the state machine through a loss, the away pose,
sleeping and a redeem on an injected clock (so it takes seconds), renders
rung 0 on the real head through the real expression engine, and prints what
happened as JSON. It records nothing and claims no measurement: it exists so
a person can watch the cues on the unit and so the CPU rows below have a
known-good harness. It does not touch the hub or the network.

On the unit (apps venv, the body app stopped so the head is free)::

    curl -X POST http://localhost:8000/api/apps/stop-current-app
    /venvs/apps_venv/bin/python scripts/link_ladder_unit_check.py --host localhost --port 8000

``--away-after-s`` and ``--tracking-off-after-s`` set the rung 0 settings the
run uses (the app's own defaults are UNMEASURED placeholders; choosing them is
the owner's call after watching this).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient  # noqa: E402
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE  # noqa: E402
from maipai_body.expression.engine import ExpressionEngine  # noqa: E402
from maipai_body.expression.suppression import SuppressionContext  # noqa: E402
from maipai_body.link.rung0 import Rung0Cues, Rung0Settings  # noqa: E402
from maipai_body.link.state_machine import LinkStateMachine  # noqa: E402


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--away-after-s", type=float, default=10.0)
    parser.add_argument("--tracking-off-after-s", type=float, default=20.0)
    parser.add_argument("--pause-s", type=float, default=2.0, help="real seconds between steps")
    args = parser.parse_args(argv)

    clock = _Clock()
    machine = LinkStateMachine(clock=clock, sleep_after_s=args.tracking_off_after_s + 10.0)
    client = ReachyMiniClient(REACHY_MINI_PROFILE, host=args.host, port=args.port)
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    rendered: list[str] = []

    def render(primitive: str) -> bool:
        outcome = engine.render_ambient(primitive, SuppressionContext())
        if outcome.rendered:
            rendered.append(primitive)
        return outcome.rendered

    cues = Rung0Cues(
        machine=machine,
        clock=clock,
        render=render,
        settings=Rung0Settings(args.away_after_s, args.tracking_off_after_s),
    )
    steps: list[dict] = []

    def note(what: str) -> None:
        steps.append(
            {
                "step": what,
                "phase": machine.phase.value,
                "tracking_allowed": cues.tracking_allowed(),
                "rendered_so_far": list(rendered),
            }
        )
        time.sleep(args.pause_s)

    try:
        machine.link_lost("unit check")
        cues.tick()
        note("link lost: settle and breathe")
        clock.now += args.away_after_s
        cues.tick()
        note("away pose")
        clock.now += args.tracking_off_after_s
        machine.tick()
        cues.tick()
        note("sleeping")
        machine.redeemed("lan", None)
        cues.tick()
        note("redeemed: the stir")
    finally:
        client.disconnect()
    json.dump(steps, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
