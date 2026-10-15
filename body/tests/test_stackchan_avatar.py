"""Avatar channel behavior against the local fake StackChan peer."""

from __future__ import annotations

import json
import unittest

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from maipai_body.bodies.stackchan.avatar.codec import decode_frame, encode_frame
from maipai_body.bodies.stackchan.avatar.server import AvatarServer
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from tests.stackchan_sim.avatar_peer import AvatarPeer
from tests.stackchan_sim.camera_sender import jpeg_frame


class StackChanAvatarTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.pairing = PairingStore()
        self.client_id = "00000000-0000-4000-8000-000000000015"
        self.device_id = "02:00:00:00:00:15"
        self.pairing.request(self.device_id, self.client_id)
        self.token = self.pairing.approve(self.device_id, self.client_id)
        self.app = AvatarServer(self.pairing)
        self.server = await serve(self.app.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{self.port}/stackChan/ws?deviceType=StackChan"

    async def asyncTearDown(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    def peer(self, *, device_id=None, client_id=None, token=None):
        return AvatarPeer(
            self.url,
            device_id or self.device_id,
            client_id or self.client_id,
            token or self.token,
        )

    async def test_expression_frame_reaches_the_peer(self):
        peer = self.peer()
        await peer.connect()
        try:
            await self.app.send_expression(self.device_id, "happy")
            frame = decode_frame(await peer.recv_frame())
            self.assertEqual(frame.kind, 0x03)
            payload = json.loads(frame.payload)
            self.assertEqual(payload["leftEye"], {"weight": 72, "rotation": 1550})
            self.assertEqual(payload["rightEye"], {"weight": 72, "rotation": -1550})
            self.assertIn("mouth", payload)
        finally:
            await peer.close()

    async def test_unpaired_device_refused(self):
        peer = self.peer(
            device_id="02:00:00:00:00:16",
            client_id="00000000-0000-4000-8000-000000000016",
        )
        try:
            await peer.connect()
            self.fail("unpaired device connected")
        except ConnectionClosed:
            pass
        self.assertEqual(self.pairing.pending()[0].device_id, "02:00:00:00:00:16")

    async def test_estop_latch_blocks_motion_frames(self):
        peer = self.peer()
        await peer.connect()
        try:
            self.app.estop_engaged = True
            await peer.websocket.send(encode_frame(0x04, b'{"yaw":20}'))
            await self.app.send_expression(self.device_id, "neutral")
            frame = decode_frame(await peer.recv_frame())
            self.assertEqual(frame.kind, 0x03)
            self.assertIsNotNone(self.app._sessions.get(self.device_id))
        finally:
            await peer.close()

    async def test_malformed_frame_closes_only_that_connection(self):
        peer = self.peer()
        await peer.connect()
        await peer.websocket.send(b"\x03\x00")
        try:
            await peer.websocket.recv()
            self.fail("malformed frame was accepted")
        except ConnectionClosed:
            pass
        healthy = self.peer()
        try:
            await healthy.connect()
            await self.app.send_expression(self.device_id, "neutral")
            self.assertEqual(decode_frame(await healthy.recv_frame()).kind, 0x03)
        finally:
            await peer.close()
            await healthy.close()

    async def test_camera_jpeg_frames_are_published_latest_wins_and_disconnect_clears(self):
        peer = self.peer()
        seen = []
        self.app.on_camera_frame = lambda device, data: seen.append((device, data))
        await peer.connect()
        try:
            await peer.send_camera_frame(jpeg_frame(b"first"))
            await peer.send_camera_frame(jpeg_frame(b"second"))
            await self.app.wait_for_camera_frame(self.device_id)
            self.assertEqual(seen[-1], (self.device_id, jpeg_frame(b"second")))
            self.assertEqual(self.app.camera_frame_count, 1)
        finally:
            await peer.close()
        await self.app.wait_for_camera_disconnect(self.device_id)
        self.assertIsNone(self.app.pop_camera_frame(self.device_id))

    async def test_malformed_camera_payload_does_not_close_session(self):
        peer = self.peer()
        await peer.connect()
        try:
            await peer.send_camera_frame(b"not-jpeg")
            await peer.send_camera_frame(jpeg_frame(b"valid"))
            await self.app.wait_for_camera_frame(self.device_id)
            self.assertEqual(self.app.pop_camera_frame(self.device_id), jpeg_frame(b"valid"))
            self.assertIsNotNone(self.app._sessions.get(self.device_id))
        finally:
            await peer.close()

    def test_frame_codec_rejects_truncated_and_mismatched_frames(self):
        self.assertEqual(decode_frame(encode_frame(3, b"{}")).payload, b"{}")
        with self.assertRaises(ValueError):
            decode_frame(b"\x03\x00")
        with self.assertRaises(ValueError):
            decode_frame(b"\x03\x00\x00\x00\x03{}")
