#!/usr/bin/env python3
"""Record the Reachy Mini fixtures against a running simulator daemon.

Usage, with the simulator already serving on localhost:8000
(`MUJOCO_GL=egl reachy-mini-daemon --sim --headless --scene empty
--no-media --fastapi-port 8000`)::

    uv run python scripts/record_fixtures.py

Writes `maipai_body/bodies/reachy_mini/fixtures/openapi.json`,
`daemon_status.json` and `state_frames.jsonl`, and prints the sha256 of
each for the fixtures README.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path

import requests
import websockets

DAEMON_URL = "http://localhost:8000"
FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent / "maipai_body" / "bodies" / "reachy_mini" / "fixtures"
)


async def _record_state_frames() -> list[dict]:
    frames: list[dict] = []
    url = "ws://localhost:8000/api/state/ws/full?frequency=20&with_doa=true&with_imu=true"
    async with websockets.connect(url) as ws:
        for _ in range(10):
            frames.append(json.loads(await ws.recv()))

        response = requests.post(
            f"{DAEMON_URL}/api/move/goto",
            json={
                "head_pose": {"x": 0, "y": 0, "z": 0, "roll": 0, "pitch": 0.2, "yaw": 0.3},
                "antennas": [0.1, -0.1],
                "body_yaw": 0.1,
                "duration": 1.0,
                "interpolation": "minjerk",
            },
            timeout=5,
        )
        response.raise_for_status()

        for _ in range(30):
            frames.append(json.loads(await ws.recv()))
    return frames


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    status_response = requests.get(f"{DAEMON_URL}/api/daemon/status", timeout=5)
    (FIXTURES_DIR / "daemon_status.json").write_bytes(status_response.content)

    openapi_response = requests.get(f"{DAEMON_URL}/openapi.json", timeout=5)
    (FIXTURES_DIR / "openapi.json").write_bytes(openapi_response.content)

    frames = asyncio.run(_record_state_frames())
    with (FIXTURES_DIR / "state_frames.jsonl").open("w") as f:
        for frame in frames:
            frame["_t_monotonic_ns"] = time.monotonic_ns()
            f.write(json.dumps(frame) + "\n")

    print(f"daemon version: {status_response.json()['version']}")
    for name in ("openapi.json", "daemon_status.json", "state_frames.jsonl"):
        digest = hashlib.sha256((FIXTURES_DIR / name).read_bytes()).hexdigest()
        print(f"{name}: {digest}")


if __name__ == "__main__":
    main()
