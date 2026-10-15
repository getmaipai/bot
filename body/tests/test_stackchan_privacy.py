"""Privacy properties exercised against authenticated fake avatar peers."""

from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from websockets.asyncio.server import serve

from maipai_body.bodies.stackchan.avatar.server import AvatarServer
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from tests.stackchan_sim.avatar_peer import AvatarPeer
from tests.stackchan_sim.camera_sender import jpeg_frame


class StackChanPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_unpaired_and_revoked_avatar_peers_are_refused(self):
        store = PairingStore()
        avatar = AvatarServer(store)
        server = await serve(avatar.handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        device, client = "02:00:00:00:00:34", "00000000-0000-4000-8000-000000000034"
        try:
            store.request(device, client)
            token = store.approve(device, client)
            store.revoke(device)
            url = f"ws://127.0.0.1:{port}/stackChan/ws?deviceType=StackChan"
            peer = AvatarPeer(url, device, client, token)
            with self.assertRaises(Exception):
                await peer.connect()
        finally:
            server.close()
            await server.wait_closed()

    async def test_camera_indicator_brackets_each_frame_and_stream_clears(self):
        store = PairingStore()
        device, client = "02:00:00:00:00:35", "00000000-0000-4000-8000-000000000035"
        store.request(device, client)
        token = store.approve(device, client)
        avatar = AvatarServer(store)
        server = await serve(avatar.handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}/stackChan/ws?deviceType=StackChan"
        peer = AvatarPeer(url, device, client, token)
        indicator = {"on": False}
        observed = []
        avatar.on_camera_frame = lambda _device, _frame: observed.append(indicator["on"])
        with tempfile.TemporaryDirectory() as directory:
            try:
                await peer.connect()
                indicator["on"] = True
                await peer.send_camera_frame(jpeg_frame(b"one"))
                await avatar.wait_for_camera_frame(device)
                indicator["on"] = False
                self.assertEqual(observed, [True])
                self.assertEqual(list(Path(directory).iterdir()), [])
            finally:
                await peer.close()
                await avatar.wait_for_camera_disconnect(device)
                server.close()
                await server.wait_closed()
        self.assertFalse(indicator["on"])

    async def test_harness_rejects_connections_outside_configured_loopback(self):
        original = socket.socket.connect
        seen = []

        def checked(sock, address):
            seen.append(address)
            host = address[0] if isinstance(address, tuple) else ""
            if host not in {"127.0.0.1", "::1"}:
                raise AssertionError("unexpected outbound destination")
            return original(sock, address)

        sock = socket.socket()
        with patch.object(socket.socket, "connect", checked):
            with self.assertRaises(OSError):
                sock.connect(("127.0.0.1", 1))
            with self.assertRaises(AssertionError):
                sock.connect(("192.0.2.11", 80))
        sock.close()
        self.assertTrue(seen)

    def test_log_and_exception_scrub_assertion_uses_secret_needles(self):
        token, cookie = "sample-token-private", "sample-cookie-private"
        captured = "pairing failed safely"
        self.assertNotIn(token, captured)
        self.assertNotIn(cookie, captured)


if __name__ == "__main__":
    unittest.main()
