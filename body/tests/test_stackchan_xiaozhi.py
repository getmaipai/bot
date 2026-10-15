"""Offline fake-device protocol replay for StackChan xiaozhi."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from maipai_body.bodies.stackchan.xiaozhi.provision import generate_image, write_image
from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer


class FakeRobot:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def set_head_angles(self, yaw: int | None, pitch: int | None, speed: int = 150) -> object:
        self.calls.append(("head", yaw, pitch, speed))
        return True

    async def set_led_color(self, red: int, green: int, blue: int) -> object:
        self.calls.append(("led", red, green, blue))
        return True

    async def set_volume(self, volume: int) -> object:
        self.calls.append(("volume", volume))
        return True


class StackChanXiaozhiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.pairing = PairingStore()
        self.pairing.request("02:00:00:00:00:01", "fake-client")
        self.token = self.pairing.approve("02:00:00:00:00:01")
        self.robot = FakeRobot()
        self.audio: list[tuple[str, bytes]] = []

        async def on_audio(session: str, frame: bytes) -> None:
            self.audio.append((session, frame))

        self.app = XiaozhiServer(self.pairing, self.robot, on_audio)
        self.server = await serve(self.app.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    async def device(self):
        return await connect(
            f"ws://127.0.0.1:{self.port}",
            additional_headers={
                "Device-Id": "02:00:00:00:00:01",
                "Client-Id": "fake-client",
                "Protocol-Version": "1",
                "Authorization": f"Bearer {self.token}",
            },
        )

    async def test_fake_device_replays_hello_audio_listen_abort_and_mcp(self) -> None:
        async with await self.device() as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "hello",
                        "version": 1,
                        "features": {"mcp": True},
                        "transport": "websocket",
                        "audio_params": {
                            "format": "opus",
                            "sample_rate": 16000,
                            "channels": 1,
                            "frame_duration": 60,
                        },
                    }
                )
            )
            hello = json.loads(await ws.recv())
            self.assertEqual(hello["transport"], "websocket")
            self.assertEqual(hello["audio_params"]["sample_rate"], 24000)
            await ws.send(b"fake-opus-uplink")
            await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "manual"}))
            await ws.send(json.dumps({"type": "abort", "reason": "wake_word_detected"}))
            stopped = json.loads(await ws.recv())
            self.assertEqual(stopped["type"], "tts")
            await ws.send(
                json.dumps(
                    {
                        "type": "mcp",
                        "payload": {
                            "jsonrpc": "2.0",
                            "method": "initialize",
                            "params": {},
                            "id": 1,
                        },
                    }
                )
            )
            initialized = json.loads(await ws.recv())
            self.assertEqual(initialized["payload"]["id"], 1)
            await ws.send(
                json.dumps(
                    {
                        "type": "mcp",
                        "payload": {
                            "jsonrpc": "2.0",
                            "method": "tools/list",
                            "params": {"cursor": ""},
                            "id": 2,
                        },
                    }
                )
            )
            tools = json.loads(await ws.recv())["payload"]["result"]["tools"]
            self.assertTrue(any(tool["name"] == "self.robot.set_head_angles" for tool in tools))
            await ws.send(
                json.dumps(
                    {
                        "type": "mcp",
                        "payload": {
                            "jsonrpc": "2.0",
                            "method": "tools/call",
                            "params": {
                                "name": "self.robot.set_head_angles",
                                "arguments": {"yaw": 12, "pitch": 40},
                            },
                            "id": 3,
                        },
                    }
                )
            )
            called = json.loads(await ws.recv())
            self.assertFalse(called["payload"]["result"]["isError"])
            self.assertIn(("head", 12, 40, 150), self.robot.calls)
            await self.app.send_audio("02:00:00:00:00:01", [b"opus-frame-1", b"opus-frame-2"])
            self.assertEqual(json.loads(await ws.recv())["state"], "start")
            self.assertEqual(await ws.recv(), b"opus-frame-1")
            self.assertEqual(await ws.recv(), b"opus-frame-2")
            self.assertEqual(json.loads(await ws.recv())["state"], "stop")
        self.assertEqual(self.audio[0][1], b"fake-opus-uplink")

    async def test_unknown_device_is_refused_and_queued_for_approval(self) -> None:
        async with connect(
            f"ws://127.0.0.1:{self.port}",
            additional_headers={"Device-Id": "02:00:00:00:00:02", "Client-Id": "new-client"},
        ) as ws:
            with self.assertRaises(Exception) as caught:
                await ws.recv()
            self.assertIn("approve this Device-Id", str(caught.exception))
        self.assertEqual(self.pairing.pending()[0].device_id, "02:00:00:00:00:02")

    async def test_pairing_token_is_bound_to_client_id(self) -> None:
        self.assertFalse(self.pairing.authorize("02:00:00:00:00:01", "other-client", self.token))

    async def test_pairing_persists_only_token_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "pairing.json"
            store = PairingStore(path)
            store.request("02:00:00:00:00:03", "persisted-client")
            token = store.approve("02:00:00:00:00:03")
            loaded = PairingStore(path)
            self.assertTrue(loaded.authorize("02:00:00:00:00:03", "persisted-client", token))
            self.assertNotIn(token, path.read_text())

    async def test_tool_call_rejects_out_of_range_values(self) -> None:
        async with await self.device() as ws:
            await ws.send(json.dumps({"type": "hello", "version": 1}))
            await ws.recv()
            await ws.send(
                json.dumps(
                    {
                        "type": "mcp",
                        "payload": {
                            "jsonrpc": "2.0",
                            "method": "tools/call",
                            "params": {
                                "name": "self.robot.set_head_angles",
                                "arguments": {"yaw": 999},
                            },
                            "id": 9,
                        },
                    }
                )
            )
            response = json.loads(await ws.recv())["payload"]
            self.assertEqual(response["error"]["code"], -32602)
            self.assertIn("Yaw must be an integer", response["error"]["message"])


class ProvisioningTests(unittest.TestCase):
    def test_generates_expected_nvs_image_via_partition_generator(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_generator = root / "generator.py"
            fake_generator.write_text(
                "import pathlib, sys\n"
                "pathlib.Path(sys.argv[3]).write_bytes(b'x' * int(sys.argv[4], 0))\n"
            )
            output = generate_image(
                root / "nvs.bin",
                websocket_url="ws://192.0.2.10:8765",
                token="unit-token",
                version="1",
                ota_url="http://192.0.2.10:8765/ota",
                partition_size=4096,
                generator=str(fake_generator),
            )
            self.assertEqual(output.stat().st_size, 4096)
            called: list[list[str]] = []

            def fake_run(command, **kwargs):
                called.append(command)
                return type("Result", (), {"returncode": 0})()

            with patch("maipai_body.bodies.stackchan.xiaozhi.provision.subprocess.run", fake_run):
                write_image(output, port="/dev/fake-usb", esptool="esptool.py")
            self.assertIn("write_flash", called[0])
            self.assertIn("/dev/fake-usb", called[0])


if __name__ == "__main__":
    unittest.main()
