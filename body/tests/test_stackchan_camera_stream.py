"""StackChan streamed frames reach the host vision bridge in memory."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

import numpy as np

from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.avatar.server import AvatarServer
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.vision_bridge import StackChanVisionBridge
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from maipai_body.hal.seam import FaceTrackTarget
from tests.stackchan_sim.avatar_peer import AvatarPeer
from tests.stackchan_sim.camera_sender import jpeg_frame


class StackChanCameraStreamTests(unittest.TestCase):
    def test_bridge_tracks_fresh_stream_frame_only_while_indicator_is_on(self):
        events = []
        camera = SimpleNamespace(stream_frame=lambda deadline: b"jpeg-bytes")
        robot = SimpleNamespace(camera=camera)
        detector = SimpleNamespace(
            detect=lambda frame: (
                events.append(("detect", frame.shape)) or [SimpleNamespace(bbox=(25, 25, 50, 50))]
            )
        )
        head = SimpleNamespace(
            goto=lambda **kwargs: events.append(("goto", kwargs)),
            hold=lambda: None,
        )
        robot.head = head
        robot.lease_holder = ""
        robot.lease = SimpleNamespace(acquire=lambda **kwargs: None, release=lambda **kwargs: None)
        bridge = StackChanVisionBridge(
            robot,
            detector=detector,
            embedder=None,
            gallery=None,
            decode=lambda data: np.zeros((100, 100, 3), dtype=np.uint8),
        )
        target = bridge.track_stream_frame()
        self.assertIsInstance(target, FaceTrackTarget)
        self.assertTrue(target.detected)
        self.assertEqual(events[0], ("detect", (100, 100, 3)))
        self.assertEqual(events[1][0], "goto")

    def test_bridge_drops_stream_frame_past_deadline(self):
        times = iter((0.0, 0.2))
        robot = SimpleNamespace(camera=SimpleNamespace(stream_frame=lambda deadline: b"jpeg"))
        bridge = StackChanVisionBridge(
            robot,
            detector=SimpleNamespace(detect=lambda frame: self.fail("stale frame was detected")),
            embedder=None,
            gallery=None,
            decode=lambda data: self.fail("stale frame was decoded"),
            clock=lambda: next(times),
        )
        self.assertFalse(bridge.track_stream_frame(deadline_s=0.1).detected)


class StackChanCameraHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_peer_frame_reaches_bridge_without_a_cue(self):
        pairing = PairingStore()
        device_id = "02:00:00:00:00:15"
        client_id = "00000000-0000-4000-8000-000000000015"
        pairing.request(device_id, client_id)
        token = pairing.approve(device_id, client_id)
        avatar = AvatarServer(pairing)
        from websockets.asyncio.server import serve

        server = await serve(avatar.handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        peer = AvatarPeer(
            f"ws://127.0.0.1:{port}/stackChan/ws?deviceType=StackChan",
            device_id,
            client_id,
            token,
        )
        device = FakeStackChanDeviceClient()
        adapter = StackChanRobotAdapter(device)
        adapter.bind_avatar_camera(avatar, device_id)
        events = []
        camera_driver = adapter.robot._driver("camera")
        camera_driver._light_on = lambda: events.append(("indicator", "on"))
        camera_driver._light_off = lambda: events.append(("indicator", "off"))
        detector = SimpleNamespace(
            detect=lambda frame: (
                events.append(("detect", camera_driver._stream_indicator_active))
                or [SimpleNamespace(bbox=(25, 25, 50, 50))]
            )
        )
        bridge = StackChanVisionBridge(
            adapter.robot,
            detector=detector,
            embedder=None,
            gallery=None,
            decode=lambda data: np.zeros((100, 100, 3), dtype=np.uint8),
        )
        try:
            await peer.connect()
            await peer.send_camera_frame(jpeg_frame(b"tracked"))
            await avatar.wait_for_camera_frame(device_id)
            self.assertEqual(avatar.camera_frame_count, 1)
            self.assertEqual(avatar.camera_frames_received, 1)
            self.assertGreater(avatar.camera_bytes_received, 0)
            target = await asyncio.to_thread(bridge.track_stream_frame)
            self.assertTrue(target.detected)
            # Local watching (face tracking) shows no cue: the household's watch level governs it.
            self.assertEqual(events, [("detect", False)])
            await peer.send_camera_frame(jpeg_frame(b"pending"))
            await avatar.wait_for_camera_frame(device_id)
        finally:
            await peer.close()
            await avatar.wait_for_camera_disconnect(device_id)
            self.assertEqual(avatar.camera_frame_count, 0)
            await asyncio.to_thread(adapter.camera_disconnected)
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
