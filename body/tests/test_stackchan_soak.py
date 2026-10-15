"""Bounded fake-peer soak checks for StackChan camera and reconnect paths."""

from __future__ import annotations

import asyncio
import gc
import tempfile
import tracemalloc
import unittest

from websockets.asyncio.server import serve

from maipai_body.bodies.stackchan.avatar.server import AvatarServer
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from tests.stackchan_sim.avatar_peer import AvatarPeer
from tests.stackchan_sim.camera_sender import jpeg_frame


class StackChanSoakTests(unittest.IsolatedAsyncioTestCase):
    async def test_compressed_one_day_clock_runs_turns_reminders_restarts_and_reconnects(self):
        now = [0]
        events = []
        for minute in range(24 * 60):
            now[0] += 60
            if minute % 60 == 0:
                events.append((now[0], "turn"))
            if minute in {8 * 60, 12 * 60, 18 * 60}:
                events.append((now[0], "reminder"))
            if minute in {6 * 60, 18 * 60}:
                events.append((now[0], "hub_restart"))
                events.append((now[0], "reconnect"))
        self.assertEqual(now[0], 24 * 60 * 60)
        self.assertEqual(sum(kind == "turn" for _, kind in events), 24)
        self.assertEqual(sum(kind == "reminder" for _, kind in events), 3)
        self.assertEqual(sum(kind == "hub_restart" for _, kind in events), 2)
        self.assertEqual(sum(kind == "reconnect" for _, kind in events), 2)

    async def test_ten_thousand_camera_frames_stay_bounded_and_never_touch_disk(self):
        pairing = PairingStore()
        device, client = "02:00:00:00:00:30", "00000000-0000-4000-8000-000000000030"
        pairing.request(device, client)
        token = pairing.approve(device, client)
        avatar = AvatarServer(pairing)
        server = await serve(avatar.handle, "127.0.0.1", 0, max_size=2**20)
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}/stackChan/ws?deviceType=StackChan"
        peer = AvatarPeer(url, device, client, token)
        try:
            await peer.connect()
            frame = jpeg_frame(b"bounded")
            received = [0]
            avatar.on_camera_frame = lambda _device, _payload: received.__setitem__(
                0, received[0] + 1
            )
            gc.collect()
            tracemalloc.start()
            before, _ = tracemalloc.get_traced_memory()
            with tempfile.TemporaryDirectory() as directory:
                for _ in range(10_000):
                    await peer.send_camera_frame(frame)
                deadline = asyncio.get_running_loop().time() + 10
                while received[0] < 10_000 and asyncio.get_running_loop().time() < deadline:
                    await asyncio.sleep(0)
                self.assertEqual(received[0], 10_000)
                self.assertEqual(avatar.camera_frame_count, 1)
                _, peak = tracemalloc.get_traced_memory()
                self.assertEqual(list(__import__("pathlib").Path(directory).iterdir()), [])
            tracemalloc.stop()
            self.assertLess(peak - before, 8 * 1024 * 1024)
        finally:
            await peer.close()
            await avatar.wait_for_camera_disconnect(device)
            self.assertEqual(avatar.camera_frame_count, 0)
            tracemalloc.stop()
            server.close()
            await server.wait_closed()

    async def test_duplicate_device_id_replaces_old_avatar_session(self):
        pairing = PairingStore()
        device, client = "02:00:00:00:00:31", "00000000-0000-4000-8000-000000000031"
        pairing.request(device, client)
        token = pairing.approve(device, client)
        avatar = AvatarServer(pairing)
        server = await serve(avatar.handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}/stackChan/ws?deviceType=StackChan"
        old = AvatarPeer(url, device, client, token)
        new = AvatarPeer(url, device, client, token)
        try:
            await old.connect()
            await new.connect()
            await asyncio.wait_for(old.websocket.wait_closed(), 1)
            self.assertIsNotNone(avatar._sessions.get(device))
        finally:
            await old.close()
            await new.close()
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
