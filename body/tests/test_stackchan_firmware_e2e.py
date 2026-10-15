"""Promise tests for a firmware-shaped StackChan client talking to the real service."""

from __future__ import annotations

import asyncio
import math
import time
import unittest

from stackchan_sim import StackChanFirmware
from websockets.asyncio.server import serve

from maipai_body.bodies.stackchan.adapter import create_stackchan_robot
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient, XiaozhiServer
from maipai_body.hal.errors import BodyLost, EstopEngaged
from maipai_body.hal.seam import HeadPose


class StackChanFirmwareEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.pairing = PairingStore()
        self.audio: list[tuple[str, bytes]] = []

        async def on_audio(session: str, frame: bytes) -> None:
            self.audio.append((session, frame))

        self.service = XiaozhiServer(self.pairing, None, on_audio)
        self.server = await serve(self.service.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{self.port}"
        self.firmware: list[StackChanFirmware] = []

    async def asyncTearDown(self) -> None:
        for device in self.firmware:
            device.resume_close_response()
            await device.stop()
        self.server.close()
        await self.server.wait_closed()

    def pair(self, device_id: str, client_id: str) -> str:
        self.pairing.request(device_id, client_id)
        return self.pairing.approve(device_id, client_id)

    def make_firmware(self, token: str | None, **kwargs) -> StackChanFirmware:
        device = StackChanFirmware(self.url, token, **kwargs)
        self.firmware.append(device)
        return device

    def make_robot(self):
        return create_stackchan_robot(XiaozhiDeviceClient(self.service))

    async def wait_until(self, predicate, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            await asyncio.sleep(0.005)
        if not predicate():
            self.fail("condition did not become true before the test deadline")

    async def test_unpaired_firmware_is_refused_then_connects_after_identity_approval(self):
        device_id = "02:00:00:00:00:51"
        client_id = "00000000-0000-4000-8000-000000000051"
        device = self.make_firmware(None, device_id=device_id, client_id=client_id)
        await device.start()
        await self.wait_until(lambda: bool(self.pairing.pending()))

        self.assertFalse(device.connected.is_set())
        self.assertEqual(
            {(entry.device_id, entry.client_id) for entry in self.pairing.pending()},
            {(device_id, client_id)},
        )
        token = self.pairing.approve(device_id, client_id)
        device.set_token(token)
        await device.wait_connected()
        self.assertEqual(device.server_hello["type"], "hello")

    async def test_firmware_initializes_lists_tools_answers_ping_and_audio_frames(self):
        token = self.pair("02:00:00:00:00:52", "00000000-0000-4000-8000-000000000052")
        device = self.make_firmware(
            token,
            device_id="02:00:00:00:00:52",
            client_id="00000000-0000-4000-8000-000000000052",
        )
        await device.start()
        await device.wait_connected()
        websocket = self.service._sessions[device.device_id]
        session_id = self.service._session_ids[device.device_id]

        for request_id, method in ((700, "initialize"), (701, "tools/list")):
            await self.service._json(
                websocket,
                session_id,
                "mcp",
                {"payload": {"jsonrpc": "2.0", "id": request_id, "method": method}},
            )

        await self.wait_until(
            lambda: 700 in device.device_mcp_responses and 701 in device.device_mcp_responses
        )
        self.assertEqual(
            device.device_mcp_responses[700]["result"]["serverInfo"]["name"], "StackChan"
        )
        listed = {tool["name"] for tool in device.device_mcp_responses[701]["result"]["tools"]}
        self.assertEqual(
            listed,
            {
                "self.robot.get_head_angles",
                "self.robot.set_head_angles",
                "self.robot.set_led_color",
                "self.audio_speaker.set_volume",
            },
        )
        client = XiaozhiDeviceClient(self.service)
        await asyncio.to_thread(client.set_led_color, 12, 34, 56)
        await asyncio.to_thread(client.set_volume, 42)
        self.assertEqual(device.led_color, (12, 34, 56))
        self.assertEqual(device.volume, 42)

        ping_id = await device.ping()
        self.assertEqual((await device.wait_mcp_response(ping_id))["result"], {})
        await device.send_audio_uplink()
        await self.wait_until(lambda: bool(self.audio))
        self.assertGreaterEqual(len(device.audio_uplink[0]), 120)
        self.assertEqual(self.audio[0][1], device.audio_uplink[0])
        device.tts_frames.clear()
        await self.service.send_audio(device.device_id, [b"\xf8\xff\xfe" + b"d" * 117])
        await self.wait_until(lambda: bool(device.audio_downlink) and len(device.tts_frames) >= 2)
        self.assertEqual(device.audio_downlink[0], b"\xf8\xff\xfe" + b"d" * 117)
        self.assertEqual(device.tts_frames[0]["state"], "start")
        self.assertEqual(device.tts_frames[-1]["state"], "stop")

    async def test_leased_robot_move_reaches_the_firmware_tool(self):
        device_id = "02:00:00:00:00:53"
        client_id = "00000000-0000-4000-8000-000000000053"
        device = self.make_firmware(
            self.pair(device_id, client_id), device_id=device_id, client_id=client_id
        )
        await device.start()
        await device.wait_connected()
        robot = self.make_robot()
        robot.lease.acquire("person", "end-to-end test")

        result = await asyncio.to_thread(
            robot.head.goto,
            pose=HeadPose(yaw=math.radians(90), pitch=math.radians(60)),
        )

        self.assertEqual(result["yaw"], 90)
        name, args = await device.wait_tool_call("self.robot.set_head_angles")
        self.assertEqual(name, "self.robot.set_head_angles")
        self.assertEqual(args, {"yaw": 90, "pitch": 60, "speed": 150})
        self.assertEqual(device._motion_target, {"yaw": 90.0, "pitch": 60.0})
        await asyncio.to_thread(
            robot.head.set,
            yaw=None,
            pitch=math.radians(45),
        )
        self.assertEqual(device.tool_calls[-1][1], {"yaw": -9999, "pitch": 45, "speed": 150})
        self.assertEqual(device._motion_target["yaw"], 90.0)

    async def test_firmware_reconnects_with_backoff_after_a_dropped_socket(self):
        device_id = "02:00:00:00:00:61"
        client_id = "00000000-0000-4000-8000-000000000061"
        device = self.make_firmware(
            self.pair(device_id, client_id), device_id=device_id, client_id=client_id
        )
        await device.start()
        await device.wait_connected()
        old_session = self.service._session_ids[device_id]

        self.service._sessions[device_id].transport.abort()
        await device.wait_connections(2)
        await device.wait_connected()

        self.assertNotEqual(self.service._session_ids[device_id], old_session)
        self.assertGreaterEqual(device.connection_count, 2)

    async def test_estop_retargets_firmware_motion_to_current_angles_and_latches(self):
        device_id = "02:00:00:00:00:54"
        client_id = "00000000-0000-4000-8000-000000000054"
        device = self.make_firmware(
            self.pair(device_id, client_id), device_id=device_id, client_id=client_id
        )
        await device.start()
        await device.wait_connected()
        robot = self.make_robot()
        robot.lease.acquire("person", "end-to-end test")
        await asyncio.to_thread(
            robot.head.goto,
            pose=HeadPose(yaw=math.radians(120), pitch=math.radians(70)),
        )
        await asyncio.sleep(0.08)
        self.assertGreater(device._motion_duration, 0.5)

        await asyncio.to_thread(robot.emergency_stop)

        calls_before_stop = [
            call for call in device.tool_calls if call[0] == "self.robot.set_head_angles"
        ]
        stop_target, _angles_at_retarget = device.motion_commands[-1]
        stop_angles = device.angle_reads[-1]
        stop_args = calls_before_stop[-1][1]
        self.assertEqual(stop_args["yaw"], stop_angles["yaw"])
        self.assertEqual(stop_args["pitch"], stop_angles["pitch"])
        self.assertEqual(stop_target, stop_angles)
        await asyncio.sleep(0.01)
        self.assertEqual(device.current_angles, stop_angles)
        self.assertTrue(robot.estop.engaged)
        with self.assertRaises(EstopEngaged):
            await asyncio.to_thread(
                robot.head.goto,
                pose=HeadPose(yaw=math.radians(0), pitch=math.radians(45)),
            )

    async def test_robot_host_call_while_firmware_is_disconnected_raises_body_lost_fix(self):
        device_id = "02:00:00:00:00:55"
        client_id = "00000000-0000-4000-8000-000000000055"
        device = self.make_firmware(
            self.pair(device_id, client_id), device_id=device_id, client_id=client_id
        )
        await device.start()
        await device.wait_connected()
        await device.stop()
        await self.wait_until(lambda: device_id not in self.service._sessions)

        with self.assertRaises(BodyLost) as raised:
            await asyncio.to_thread(XiaozhiDeviceClient(self.service).set_volume, 40)
        self.assertIn("Reconnect it and retry", str(raised.exception))
        self.assertIn("retry", str(raised.exception))

    async def test_stale_session_replacement_survives_a_half_open_firmware_peer(self):
        device_id = "02:00:00:00:00:56"
        client_id = "00000000-0000-4000-8000-000000000056"
        token = self.pair(device_id, client_id)
        first = self.make_firmware(token, device_id=device_id, client_id=client_id)
        second = self.make_firmware(token, device_id=device_id, client_id=client_id)
        await first.start()
        await first.wait_connected()
        old_session = self.service._session_ids[device_id]
        first.hold_close_response()

        await second.start()
        await second.wait_connected()

        self.assertNotEqual(self.service._session_ids[device_id], old_session)
        self.assertEqual(len([key for key in self.service._sessions if key == device_id]), 1)
        await asyncio.sleep(0.15)
        first.resume_close_response()
        await first.disconnected.wait()

    async def test_rate_limit_does_not_lock_out_an_already_pending_firmware_identity(self):
        device_id = "02:00:00:00:00:57"
        client_id = "00000000-0000-4000-8000-000000000057"
        device = self.make_firmware(None, device_id=device_id, client_id=client_id)
        await device.start()
        await self.wait_until(lambda: bool(self.pairing.pending()))
        self.service._source_requests["127.0.0.1"] = [time.monotonic()] * 8
        previous_close_count = len(device.close_reasons)
        next_attempt = device.connection_count + 1
        await device.wait_connections(next_attempt)
        await self.wait_until(lambda: len(device.close_reasons) > previous_close_count)

        self.assertTrue(
            any(
                row.device_id == device_id and row.client_id == client_id
                for row in self.pairing.pending()
            )
        )
        self.assertFalse(
            any(
                "Too many pairing requests" in reason
                for _, reason in device.close_reasons[previous_close_count:]
            )
        )

    async def test_revoked_token_closes_connected_firmware_after_its_next_ping(self):
        device_id = "02:00:00:00:00:58"
        client_id = "00000000-0000-4000-8000-000000000058"
        token = self.pair(device_id, client_id)
        device = self.make_firmware(token, device_id=device_id, client_id=client_id)
        await device.start()
        await device.wait_connected()
        self.pairing.revoke(device_id)

        await device.ping()
        await asyncio.wait_for(device.disconnected.wait(), timeout=1.0)
        await self.wait_until(lambda: device_id not in self.service._sessions)

        self.assertNotIn(device_id, self.service._sessions)

    async def test_patch_003_persistent_channel_stays_open_after_idle_timeout(self):
        device_id = "02:00:00:00:00:59"
        client_id = "00000000-0000-4000-8000-000000000059"
        device = self.make_firmware(
            self.pair(device_id, client_id),
            device_id=device_id,
            client_id=client_id,
            persistent_channel=True,
            idle_timeout=0.02,
        )
        await device.start()
        await device.wait_connected()
        await asyncio.sleep(0.1)

        self.assertEqual(device.connection_count, 1)
        self.assertTrue(device.connected.is_set())

    async def test_upstream_session_only_channel_reconnects_after_idle_timeout(self):
        device_id = "02:00:00:00:00:60"
        client_id = "00000000-0000-4000-8000-000000000060"
        device = self.make_firmware(
            self.pair(device_id, client_id),
            device_id=device_id,
            client_id=client_id,
            persistent_channel=False,
            idle_timeout=0.02,
            backoff=(0.08, 0.08),
        )
        await device.start()
        await device.wait_connected()

        await device.wait_connections(2)

        self.assertGreaterEqual(device.connection_count, 2)
