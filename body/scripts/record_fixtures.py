"""Record the Reachy Mini fixtures the fake replays, against a running daemon.

Usage (from ``body/``, with a `reachy-mini-daemon --sim --headless` or a
real unit reachable)::

    uv run python scripts/record_fixtures.py --host localhost --port 8000

Writes ``maipai_body/bodies/reachy_mini/fixtures/openapi.json``,
``daemon_status.json``, ``state_frames.jsonl`` and a ``README.md`` naming
the daemon version and the sha256 of ``openapi.json``. Never invents a
frame: every line in ``state_frames.jsonl`` is a real reading taken from
the daemon named on the command line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import requests

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient, daemon_state_to_sample
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.hal.seam import AntennaPositions, HeadPose

FIXTURES_DIR = Path(__file__).parent.parent / "maipai_body" / "bodies" / "reachy_mini" / "fixtures"


def _record_state_trace(client: ReachyMiniClient, frames_per_stage: int = 15) -> list[dict]:
    """Drive a short goto-then-hold sequence, recording real frames throughout.

    The recorded trace is what ``fake.py``'s "hold stops motion" test reads:
    baseline frames at rest, frames after a real ``goto``, then frames after
    a real ``hold``, so the fixture itself demonstrates settling, not a
    scripted approximation of it.
    """
    samples: list[dict] = []
    feed = client.state_feed(frequency=10.0)

    for _ in range(frames_per_stage):
        samples.append(daemon_state_to_sample(_feed_raw(feed)))

    client.goto(
        pose=HeadPose(pitch=0.2, yaw=0.3),
        antennas=AntennaPositions(left=0.4, right=-0.4),
        body_yaw=0.15,
        duration_s=1.0,
        method="minjerk",
    )
    for _ in range(frames_per_stage):
        samples.append(daemon_state_to_sample(_feed_raw(feed)))

    client.hold()
    for _ in range(frames_per_stage):
        samples.append(daemon_state_to_sample(_feed_raw(feed)))

    feed.close()
    return samples


def _feed_raw(feed) -> dict:
    """Pull one raw daemon JSON message from the feed's underlying websocket."""
    message = feed._ws.recv()
    return json.loads(message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    base = f"http://{args.host}:{args.port}"
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    openapi = requests.get(f"{base}/openapi.json", timeout=10).json()
    openapi_path = FIXTURES_DIR / "openapi.json"
    openapi_path.write_text(json.dumps(openapi, indent=2) + "\n")

    status = requests.get(f"{base}/api/daemon/status", timeout=10).json()
    (FIXTURES_DIR / "daemon_status.json").write_text(json.dumps(status, indent=2) + "\n")

    client = ReachyMiniClient(REACHY_MINI_PROFILE, host=args.host, port=args.port)
    samples = _record_state_trace(client)
    client.disconnect()

    with (FIXTURES_DIR / "state_frames.jsonl").open("w") as handle:
        for sample in samples:
            handle.write(json.dumps(sample) + "\n")

    openapi_sha256 = hashlib.sha256(openapi_path.read_bytes()).hexdigest()
    readme = f"""# Reachy Mini fixtures

Recorded {time.strftime("%Y-%m-%d", time.gmtime())} against
`reachy-mini-daemon` version `{status["version"]}` in simulation mode
(`--sim --headless --scene empty`), by `scripts/record_fixtures.py`.

- `openapi.json`: the daemon's OpenAPI schema. sha256: `{openapi_sha256}`
- `daemon_status.json`: one `/api/daemon/status` response.
- `state_frames.jsonl`: real state-feed samples from `/api/state/ws/full`,
  recorded across a scripted goto-then-hold sequence (baseline, moving,
  held), one JSON sample per line in the shape
  `client.daemon_state_to_sample` produces.

Never hand-edited. Re-run `record_fixtures.py` against a running daemon to
refresh.
"""
    (FIXTURES_DIR / "README.md").write_text(readme)
    print(f"Wrote fixtures to {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
