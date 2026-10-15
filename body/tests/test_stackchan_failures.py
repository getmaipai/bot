"""Keep xiaozhi error paths actionable and prove later sessions still work."""

from __future__ import annotations

import asyncio
import json
import unittest

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer


class StackChanFailureShapeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.pairing = PairingStore()
        self.device_id = "02:00:00:00:00:20"
        self.client_id = "00000000-0000-4000-8000-000000000020"
        self.pairing.request(self.device_id, self.client_id)
        self.token = self.pairing.approve(self.device_id)
        self.health_id = "02:00:00:00:00:21"
        self.health_client = "00000000-0000-4000-8000-000000000021"
        self.pairing.request(self.health_id, self.health_client)
        self.health_token = self.pairing.approve(self.health_id)
        robot = StackChanRobotAdapter(FakeStackChanDeviceClient())
        self.service = XiaozhiServer(self.pairing, robot, idle_timeout=0.05)
        self.server = await serve(self.service.handle, "127.0.0.1", 0, max_size=2**20)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    async def open_device(self, *, device_id=None, client_id=None, token=None):
        return await connect(
            f"ws://127.0.0.1:{self.port}",
            additional_headers={
                "Device-Id": device_id or self.device_id,
                "Client-Id": client_id or self.client_id,
                "Protocol-Version": "1",
                "Authorization": f"Bearer {self.token if token is None else token}",
            },
        )

    async def assert_service_stays_up(self) -> None:
        async with await self.open_device(
            device_id=self.health_id, client_id=self.health_client, token=self.health_token
        ) as websocket:
            await websocket.send(json.dumps({"type": "hello", "version": 1}))
            response = json.loads(await asyncio.wait_for(websocket.recv(), timeout=1))
            self.assertEqual(response["type"], "hello")

    async def test_unapproved_device_gets_next_step_and_service_stays_up(self) -> None:
        async with await self.open_device(
            device_id="02:00:00:00:00:22",
            client_id="00000000-0000-4000-8000-000000000022",
            token="unused",
        ) as websocket:
            with self.assertRaises(ConnectionClosed) as caught:
                await websocket.recv()
        reason = caught.exception.rcvd.reason
        self.assertIn("Device is not approved", reason)
        self.assertIn("approve this Device-Id", reason)
        await self.assert_service_stays_up()

    async def test_bad_token_gets_pairing_instruction_and_service_stays_up(self) -> None:
        async with await self.open_device(token="wrong-token") as websocket:
            with self.assertRaises(ConnectionClosed) as caught:
                await websocket.recv()
        reason = caught.exception.rcvd.reason
        self.assertIn("Device is not approved", reason)
        self.assertIn("provision its token", reason)
        await self.assert_service_stays_up()

    async def test_malformed_json_gets_correction_and_service_stays_up(self) -> None:
        async with await self.open_device() as websocket:
            await websocket.send("{not-json")
            response = json.loads(await websocket.recv())
            self.assertEqual(response["type"], "error")
            message = response["message"]
            self.assertIn("Invalid JSON", message)
            self.assertIn("Send a xiaozhi JSON text frame", message)
            await websocket.send(json.dumps({"type": "hello"}))
            self.assertEqual(json.loads(await websocket.recv())["type"], "hello")
        await self.assert_service_stays_up()

    async def test_dropped_connection_logs_next_step_and_service_stays_up(self) -> None:
        websocket = await self.open_device()
        await websocket.send(json.dumps({"type": "hello"}))
        self.assertEqual(json.loads(await websocket.recv())["type"], "hello")
        with self.assertLogs("maipai_body.bodies.stackchan.xiaozhi.server", level="INFO") as logs:
            websocket.transport.abort()
            await self.assert_service_stays_up()
        self.assertTrue(
            any("Reconnect the device and retry the turn" in row for row in logs.output)
        )

    async def test_hung_device_gets_timeout_and_next_step_and_service_stays_up(self) -> None:
        async with await self.open_device() as websocket:
            with self.assertRaises(ConnectionClosed) as caught:
                await asyncio.wait_for(websocket.recv(), timeout=1)
        self.assertEqual(caught.exception.rcvd.code, 1001)
        message = caught.exception.rcvd.reason
        self.assertIn("No xiaozhi frame arrived", message)
        self.assertIn("Send a hello frame", message)
        await self.assert_service_stays_up()

    async def test_idle_after_hello_keeps_session_for_server_audio(self) -> None:
        async with await self.open_device() as websocket:
            await websocket.send(json.dumps({"type": "hello", "version": 1}))
            hello = json.loads(await websocket.recv())
            self.assertEqual(hello["type"], "hello")

            await asyncio.sleep(self.service.idle_timeout * 2)
            await self.service.send_audio(self.device_id, [b"recorded-server-frame"])

            start = json.loads(await websocket.recv())
            self.assertEqual(start["type"], "tts")
            self.assertEqual(start["state"], "start")
            self.assertEqual(start["session_id"], hello["session_id"])
            self.assertEqual(await websocket.recv(), b"recorded-server-frame")
            stop = json.loads(await websocket.recv())
            self.assertEqual(stop["type"], "tts")
            self.assertEqual(stop["state"], "stop")
            self.assertEqual(stop["session_id"], hello["session_id"])

            await websocket.send(
                json.dumps(
                    {
                        "type": "mcp",
                        "payload": {"jsonrpc": "2.0", "method": "ping", "id": 8},
                    }
                )
            )
            self.assertEqual(json.loads(await websocket.recv())["payload"]["id"], 8)

        await self.assert_service_stays_up()

    async def test_replayed_hello_gets_next_step_and_service_stays_up(self) -> None:
        async with await self.open_device() as websocket:
            frame = json.dumps({"type": "hello", "version": 1})
            await websocket.send(frame)
            first = json.loads(await websocket.recv())
            await websocket.send(frame)
            replay = json.loads(await websocket.recv())
            self.assertEqual(replay["type"], "error")
            self.assertEqual(replay["session_id"], first["session_id"])
            self.assertIn("Repeated hello frame", replay["message"])
            self.assertIn("Continue using the active session", replay["message"])
            await websocket.send(
                json.dumps(
                    {
                        "type": "mcp",
                        "payload": {"jsonrpc": "2.0", "method": "ping", "id": 7},
                    }
                )
            )
            self.assertEqual(json.loads(await websocket.recv())["payload"]["id"], 7)
        await self.assert_service_stays_up()

    async def test_oversized_frame_logs_next_step_and_service_stays_up(self) -> None:
        websocket = await self.open_device()
        with self.assertLogs(
            "maipai_body.bodies.stackchan.xiaozhi.server", level="WARNING"
        ) as logs:
            await websocket.send("x" * ((2**20) + 1))
            with self.assertRaises(ConnectionClosed) as caught:
                await websocket.recv()
            await self.assert_service_stays_up()
        self.assertEqual(caught.exception.rcvd.code, 1009)
        self.assertIn("frame", caught.exception.rcvd.reason.lower())
        self.assertTrue(any("Send smaller frames and reconnect" in row for row in logs.output))
