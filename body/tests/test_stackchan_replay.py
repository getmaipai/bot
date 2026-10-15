"""Replay recorded xiaozhi frames through the service and shared robot object."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer

FIXTURES = Path(__file__).parent / "fixtures" / "stackchan"


class StackChanReplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.pairing = PairingStore()
        self.device_id = "02:00:00:00:00:10"
        self.client_id = "00000000-0000-4000-8000-000000000010"
        self.pairing.request(self.device_id, self.client_id)
        self.token = self.pairing.approve(self.device_id)
        self.device = FakeStackChanDeviceClient()
        self.adapter = StackChanRobotAdapter(self.device)
        self.service = XiaozhiServer(self.pairing, self.adapter)
        self.server = await serve(self.service.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    async def test_recorded_frames_reach_stackchan_robot_object(self) -> None:
        frames = json.loads((FIXTURES / "replay.json").read_text(encoding="utf-8"))
        for frame in frames:
            if "device_reply" in frame:
                self.assertIs(type(frame["device_reply"]["payload"]["id"]), int)
        async with await connect(
            f"ws://127.0.0.1:{self.port}",
            additional_headers={
                "Device-Id": self.device_id,
                "Client-Id": self.client_id,
                "Protocol-Version": "1",
                "Authorization": f"Bearer {self.token}",
            },
        ) as websocket:
            for frame in frames:
                if "send" not in frame:
                    continue
                await websocket.send(json.dumps(frame["send"]))
                response = json.loads(await websocket.recv())
                expected = frame["expect"]
                self.assertEqual(response["type"], expected["type"])
                if expected["type"] == "hello":
                    self.assertEqual(response["transport"], expected["transport"])
                    self.assertEqual(response["version"], expected["version"])
                elif expected["type"] == "tts":
                    self.assertEqual(response["state"], expected["state"])
                    self.assertTrue(response.get("session_id"))
                elif expected["type"] == "mcp":
                    payload = response["payload"]
                    self.assertEqual(payload["id"], expected["id"])
                    if "result_key" in expected:
                        self.assertIn(expected["result_key"], payload["result"])
                    if "result_is_error" in expected:
                        self.assertEqual(payload["result"]["isError"], expected["result_is_error"])
                self.assertNotIn("robot_call", frame)
