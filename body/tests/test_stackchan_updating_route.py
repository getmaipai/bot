"""Loopback routes Home calls around a firmware flash (owner request 2026-10-20)."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request

from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer


class _Socket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, data):
        self.sent.append(json.loads(data))


def _call(base, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data, headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_updating_and_updated_reach_the_device_as_system_commands():
    json_header = {"Content-Type": "application/json"}

    async def scenario(tmp) -> tuple[list[dict], list[tuple[int, dict]]]:
        server = XiaozhiServer(PairingStore(tmp / "p.json"), robot=None, vision_port=0)
        socket = _Socket()
        server._sessions["d"] = socket
        server._session_ids["d"] = "sid"
        await server.start("127.0.0.1", 0)
        base = f"http://127.0.0.1:{server.vision_port}"
        results = []
        try:
            for path, body in (
                ("/robot/updating", {"version": "0.2.7", "progress": 40}),
                ("/robot/updating", {"version": None, "progress": None}),
                ("/robot/updating", {}),
                ("/robot/updated", {}),
                ("/robot/updating", {"version": "bad version!"}),
                ("/robot/updating", {"progress": 101}),
                ("/robot/updating", {"progress": True}),
            ):
                results.append(await asyncio.to_thread(_call, base, path, body, json_header))
            results.append(await asyncio.to_thread(_call, base, "/robot/updated", {}, {}))
            results.append(
                await asyncio.to_thread(
                    _call,
                    base,
                    "/robot/updated",
                    {},
                    {**json_header, "Origin": "http://evil.example"},
                )
            )
        finally:
            await server.close()
        return socket.sent, results

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        sent, results = asyncio.run(scenario(Path(directory)))
    statuses = [status for status, _ in results]
    assert statuses == [200, 200, 200, 200, 400, 400, 400, 415, 403]
    assert [(m["type"], m["command"]) for m in sent] == [("system", "updating")] * 3 + [
        ("system", "updated")
    ]
    assert sent[0]["version"] == "0.2.7" and sent[0]["progress"] == 40
    assert "version" not in sent[1] and "progress" not in sent[1]  # nulls are left out


def test_with_no_robot_connected_the_routes_say_so_in_plain_words():
    async def scenario(tmp):
        server = XiaozhiServer(PairingStore(tmp / "p.json"), robot=None, vision_port=0)
        await server.start("127.0.0.1", 0)
        base = f"http://127.0.0.1:{server.vision_port}"
        try:
            return await asyncio.to_thread(
                _call,
                base,
                "/robot/updating",
                {"version": "0.2.7"},
                {"Content-Type": "application/json"},
            )
        finally:
            await server.close()

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        status, body = asyncio.run(scenario(Path(directory)))
    assert status == 503 and "No StackChan is connected" in body["error"]
