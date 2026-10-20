"""Tests for StackChanFirmware listen frames and real Opus uplink streaming."""

from __future__ import annotations

import asyncio
import json
import time
import unittest

import av
import numpy as np
from stackchan_sim import StackChanFirmware
from websockets.asyncio.server import serve


class SimUplinkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.messages: list[str | bytes] = []

        async def handler(ws):
            try:
                await ws.recv()
                await ws.send(json.dumps({"type": "hello", "version": 1}))
                while True:
                    msg = await ws.recv()
                    self.messages.append(msg)
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

    async def wait_messages(self, count: int, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        while len(self.messages) < count and time.monotonic() < deadline:
            await asyncio.sleep(0.005)
        if len(self.messages) < count:
            self.fail(f"expected {count} messages, got {len(self.messages)}")

    async def test_send_listen_start_realtime_with_aec(self) -> None:
        await self.device.send_listen("start", "realtime", aec=True)
        await self.wait_messages(1)
        self.assertEqual(
            json.loads(self.messages[0]),
            {"type": "listen", "state": "start", "mode": "realtime", "aec": True},
        )

    async def test_send_listen_detect_defaults(self) -> None:
        await self.device.send_listen("detect")
        await self.wait_messages(1)
        msg = json.loads(self.messages[0])
        self.assertEqual(msg["type"], "listen")
        self.assertEqual(msg["state"], "detect")
        self.assertEqual(msg["mode"], "auto")
        self.assertNotIn("aec", msg)

    async def test_stream_opus_delivers_five_packets(self) -> None:
        self.messages.clear()
        self.device.uplink_log.clear()
        await self.device.stream_opus(5)
        await self.wait_messages(5)
        binary = [m for m in self.messages if isinstance(m, bytes)]
        self.assertEqual(len(binary), 5)
        self.assertEqual(len(self.device.uplink_log), 5)
        times = [t for t, _ in self.device.uplink_log]
        for i in range(1, len(times)):
            self.assertGreater(times[i], times[i - 1])

    async def test_stream_opus_realtime_takes_at_least_one_hundred_ms(self) -> None:
        start = time.monotonic()
        await self.device.stream_opus(3, frame_ms=60, realtime=True)
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 0.1)

    async def test_stream_opus_packets_decode_to_non_silent_audio(self) -> None:
        self.messages.clear()
        await self.device.stream_opus(5)
        await self.wait_messages(5)
        binary = [m for m in self.messages if isinstance(m, bytes)]
        self.assertTrue(binary, "no binary packets received")
        for packet in binary:
            decoder = av.CodecContext.create("opus", "r")
            decoder.sample_rate = 16000
            decoded_frames = decoder.decode(av.Packet(packet))
            has_audio = False
            for frame in decoded_frames:
                arr = frame.to_ndarray()
                if np.any(arr != 0):
                    has_audio = True
                    break
            self.assertTrue(has_audio, "decoded audio is silent")


if __name__ == "__main__":
    unittest.main()
