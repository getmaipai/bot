"""Local dashboard pairing lifecycle for a fake StackChan client."""

from __future__ import annotations

import asyncio
import http.client
import json
import math
import tempfile
import unittest
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient, XiaozhiServer
from maipai_body.dashboard.server import DashboardServer
from maipai_body.hal.seam import HeadPose


class StackChanDashboardPairingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pairing = PairingStore(Path(self.temp.name) / "pairing.json")
        self.audio_frames: list[tuple[str, bytes]] = []

        async def on_audio(session_id: str, frame: bytes) -> None:
            self.audio_frames.append((session_id, frame))

        self.xiaozhi = XiaozhiServer(self.pairing, robot=None, audio_handler=on_audio)
        self.body = StackChanRobotAdapter(XiaozhiDeviceClient(self.xiaozhi))
        self.xiaozhi.robot = self.body
        self.websocket_server = await serve(self.xiaozhi.handle, "127.0.0.1", 0)
        self.websocket_port = self.websocket_server.sockets[0].getsockname()[1]
        self.dashboard = DashboardServer(
            FakeReachyMiniClient(),
            REACHY_MINI_PROFILE,
            host="127.0.0.1",
            port=0,
            pairing_store=self.pairing,
        )
        self.dashboard.start()

    async def asyncTearDown(self) -> None:
        self.dashboard.stop()
        self.websocket_server.close()
        await self.websocket_server.wait_closed()

    async def test_refusal_approval_hello_audio_and_revoke(self) -> None:
        device_id = "02:00:00:00:00:17"
        headers = {"Device-Id": device_id, "Client-Id": "00000000-0000-4000-8000-000000000017"}
        async with connect(
            f"ws://127.0.0.1:{self.websocket_port}", additional_headers=headers
        ) as ws:
            with self.assertRaises(Exception) as refusal:
                await ws.recv()
            self.assertIn("approve this Device-Id in the dashboard", str(refusal.exception))

        pending = await asyncio.to_thread(
            _request,
            self.dashboard.port,
            "GET",
            "/api/stackchan/pairings/pending",
            None,
        )
        self.assertEqual(pending[0]["device_id"], device_id)
        self.assertEqual(pending[0]["client_id"], headers["Client-Id"])
        missing_client_status, missing_client = await asyncio.to_thread(
            _request_with_status,
            self.dashboard.port,
            "POST",
            "/api/stackchan/pairings/approve",
            {"device_id": device_id},
        )
        self.assertEqual(missing_client_status, 400)
        self.assertIn("client_id is required", missing_client["error"])
        approved = await asyncio.to_thread(
            _request,
            self.dashboard.port,
            "POST",
            "/api/stackchan/pairings/approve",
            {"device_id": device_id, "client_id": headers["Client-Id"]},
        )
        self.assertEqual(approved["client_id"], headers["Client-Id"])
        self.assertNotIn("token", approved)
        token_file = Path(approved["token_file"])
        self.assertEqual(token_file.stat().st_mode & 0o777, 0o600)
        token = token_file.read_text().strip()

        auth_headers = {
            **headers,
            "Authorization": f"Bearer {token}",
        }
        async with connect(
            f"ws://127.0.0.1:{self.websocket_port}", additional_headers=auth_headers
        ) as ws:
            await ws.send(json.dumps({"type": "hello"}))
            hello = json.loads(await ws.recv())
            self.assertEqual(hello["type"], "hello")
            self.assertEqual(hello["version"], 1)

            async def send_head_motion() -> object:
                def goto() -> object:
                    lease = self.body.robot.lease.acquire("person", "fixture")
                    try:
                        return self.body.robot.head.set(
                            pose=HeadPose(yaw=math.radians(12), pitch=math.radians(40))
                        )
                    finally:
                        self.body.robot.lease.release(lease.holder)

                return await asyncio.to_thread(goto)

            motion = asyncio.create_task(send_head_motion())
            call_frame = json.loads(await ws.recv())
            request = call_frame["payload"]
            self.assertEqual(call_frame["type"], "mcp")
            self.assertEqual(request["method"], "tools/call")
            self.assertIsInstance(request["id"], int)
            self.assertEqual(request["params"]["name"], "self.robot.set_head_angles")
            self.assertEqual(request["params"]["arguments"], {"yaw": 12, "pitch": 40, "speed": 150})
            await ws.send(
                json.dumps(
                    {
                        "type": "mcp",
                        "payload": {
                            "jsonrpc": "2.0",
                            "id": request["id"],
                            "result": {"content": [{"type": "text", "text": "true"}]},
                        },
                    }
                )
            )
            await motion

            await ws.send(b"fixture-opus-frame")
            await asyncio.sleep(0.01)
            self.assertEqual(self.audio_frames[0][1], b"fixture-opus-frame")
            revoked = await asyncio.to_thread(
                _request,
                self.dashboard.port,
                "POST",
                "/api/stackchan/pairings/revoke",
                {"device_id": device_id},
            )
            self.assertTrue(revoked["revoked"])
            await ws.send(json.dumps({"type": "hello"}))
            with self.assertRaises(Exception):
                await ws.recv()

        token_file.unlink()


def _request(port: int, method: str, path: str, body: dict | None) -> object:
    status, result = _request_with_status(port, method, path, body)
    if status != 200:
        raise AssertionError(f"dashboard API returned {status}: {result}")
    return result


def _request_with_status(port: int, method: str, path: str, body: dict | None):
    connection = http.client.HTTPConnection("127.0.0.1", port)
    payload = json.dumps(body) if body is not None else None
    headers = {"Origin": f"http://127.0.0.1:{port}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    connection.request(method, path, payload, headers)
    response = connection.getresponse()
    status = response.status
    result = json.loads(response.read())
    connection.close()
    return status, result
