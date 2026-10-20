"""Tests for firmware tool-reply latency, dropped replies, and receive timestamps."""

from __future__ import annotations

import asyncio
import json
import time
import unittest

from stackchan_sim import StackChanFirmware
from websockets.asyncio.server import ServerConnection, serve

ANGLES_REQUEST = {
    "type": "mcp",
    "payload": {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "self.robot.get_head_angles", "arguments": {}},
    },
}


class SimDownlinkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server_ws: list[ServerConnection] = []
        self.server_messages: list[tuple[float, str | bytes]] = []

        async def handler(ws: ServerConnection) -> None:
            self.server_ws.append(ws)
            try:
                await ws.recv()
                await ws.send(json.dumps({"type": "hello", "version": 1}))
                while True:
                    message = await ws.recv()
                    self.server_messages.append((time.monotonic(), message))
            except Exception:
                pass

        self.server = await serve(handler, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{self.port}"
        self.device = StackChanFirmware(self.url, None, persistent_channel=True)
        await self.device.start()
        await self.device.wait_connected()

    async def asyncTearDown(self) -> None:
        await self.device.stop()
        self.server.close()
        await self.server.wait_closed()

    async def wait_ws(self) -> ServerConnection:
        deadline = time.monotonic() + 2.0
        while not self.server_ws and time.monotonic() < deadline:
            await asyncio.sleep(0.005)
        if not self.server_ws:
            self.fail("server never recorded a firmware connection")
        return self.server_ws[0]

    async def wait_reply(self, request_id: int, timeout: float = 2.0) -> tuple[float, dict] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for stamp, message in self.server_messages:
                if not isinstance(message, str):
                    continue
                data = json.loads(message)
                if data.get("type") == "mcp" and data.get("payload", {}).get("id") == request_id:
                    return stamp, data
            await asyncio.sleep(0.005)
        return None

    async def test_tool_reply_arrives_no_sooner_than_latency(self) -> None:
        device = self.device
        device.tool_latency_s = 0.3
        ws = await self.wait_ws()
        self.server_messages.clear()
        sent_at = time.monotonic()
        await ws.send(json.dumps(ANGLES_REQUEST))
        result = await self.wait_reply(7)
        self.assertIsNotNone(result, "firmware never replied to the tool call")
        reply_at, data = result
        self.assertGreaterEqual(reply_at - sent_at, 0.25)
        self.assertIn("result", data["payload"])

    async def test_dropped_tool_reply_sends_nothing_but_records_the_call(self) -> None:
        device = self.device
        device.drop_tool_replies = frozenset({"self.robot.get_head_angles"})
        ws = await self.wait_ws()
        self.server_messages.clear()
        await ws.send(json.dumps(ANGLES_REQUEST))
        await asyncio.sleep(0.5)
        self.assertIsNone(
            self.server_reply_now(7),
            "server received a reply that the firmware was told to drop",
        )
        self.assertIn(
            ("self.robot.get_head_angles", {}),
            device.tool_calls,
        )

    def server_reply_now(self, request_id: int) -> tuple[float, dict] | None:
        for stamp, message in self.server_messages:
            if not isinstance(message, str):
                continue
            data = json.loads(message)
            if data.get("type") == "mcp" and data.get("payload", {}).get("id") == request_id:
                return stamp, data
        return None

    async def test_tts_frames_and_binary_downlink_are_timestamped(self) -> None:
        device = self.device
        ws = await self.wait_ws()
        frame_one = b"\xf8\xff\xfe" + b"a" * 100
        frame_two = b"\xf8\xff\xfe" + b"b" * 200
        await ws.send(json.dumps({"type": "tts", "state": "start"}))
        await ws.send(frame_one)
        await ws.send(frame_two)
        await ws.send(json.dumps({"type": "tts", "state": "stop"}))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if len(device.tts_events) >= 2 and len(device.downlink_log) >= 2:
                break
            await asyncio.sleep(0.005)
        self.assertGreaterEqual(len(device.tts_events), 2)
        self.assertGreaterEqual(len(device.downlink_log), 2)
        states = [data["state"] for _, data in device.tts_events[:2]]
        self.assertEqual(states, ["start", "stop"])
        times = [stamp for stamp, _ in device.tts_events[:2]]
        self.assertGreater(times[1], times[0])
        lengths = [size for _, size in device.downlink_log[:2]]
        self.assertEqual(lengths, [len(frame_one), len(frame_two)])
        self.assertEqual(device.audio_downlink[:2], [frame_one, frame_two])


if __name__ == "__main__":
    unittest.main()
