"""Offline fake-device protocol replay for StackChan xiaozhi."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from maipai_body.bodies.stackchan.xiaozhi.provision import generate_image, main, write_image
from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer


class StackChanXiaozhiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.pairing = PairingStore()
        self.pairing.request("02:00:00:00:00:01", "fake-client")
        self.token = self.pairing.approve("02:00:00:00:00:01")
        self.stackchan_client = FakeStackChanDeviceClient()
        self.robot = StackChanRobotAdapter(self.stackchan_client)
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
            self.assertEqual(self.stackchan_client.calls[-1].name, "self.robot.set_head_angles")
            self.assertEqual(
                self.stackchan_client.calls[-1].arguments,
                {"yaw": 12, "pitch": 40, "speed": 150},
            )
            await ws.send(
                json.dumps(
                    {
                        "type": "mcp",
                        "payload": {
                            "jsonrpc": "2.0",
                            "method": "tools/call",
                            "params": {
                                "name": "self.robot.set_led_color",
                                "arguments": {"red": 12, "green": 24, "blue": 36},
                            },
                            "id": 4,
                        },
                    }
                )
            )
            led_result = json.loads(await ws.recv())
            self.assertFalse(led_result["payload"]["result"]["isError"])
            self.assertEqual(self.stackchan_client.led_color, (12, 24, 36))
            await ws.send(
                json.dumps(
                    {
                        "type": "mcp",
                        "payload": {
                            "jsonrpc": "2.0",
                            "method": "tools/call",
                            "params": {
                                "name": "self.audio_speaker.set_volume",
                                "arguments": {"volume": 60},
                            },
                            "id": 5,
                        },
                    }
                )
            )
            volume_result = json.loads(await ws.recv())
            self.assertFalse(volume_result["payload"]["result"]["isError"])
            self.assertEqual(self.stackchan_client.volume, 60)
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
            self.assertIn("approve this Device-Id in the dashboard", str(caught.exception))
        self.assertEqual(self.pairing.pending()[0].device_id, "02:00:00:00:00:02")

    async def test_pairing_token_is_bound_to_client_id(self) -> None:
        self.assertFalse(self.pairing.authorize("02:00:00:00:00:01", "other-client", self.token))

    async def test_separate_pairing_stores_refresh_shared_pending_approval_and_revocation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pairing.json"
            service = PairingStore(path)
            dashboard = PairingStore(path)
            device_id = "02:00:00:00:00:42"
            client_id = "shared-client"

            request = service.request(device_id, client_id)
            self.assertEqual(dashboard.pending(), (request,))
            token_path = dashboard.approve_to_file(device_id)
            token = token_path.read_text(encoding="utf-8").strip()
            self.assertTrue(service.authorize(device_id, client_id, token))

            self.assertTrue(dashboard.revoke(device_id))
            self.assertFalse(service.authorize(device_id, client_id, token))
            token_path.unlink()

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

    def test_cli_generates_private_image_and_consumes_one_time_token_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generator = root / "generator.py"
            generator.write_text(
                "import pathlib, sys\n"
                "pathlib.Path(sys.argv[3]).write_bytes(b'x' * int(sys.argv[4], 0))\n"
            )
            token_file = root / "approved.token"
            token_file.write_text("one-time-token\n")
            token_file.chmod(0o600)
            output = root / "nvs.bin"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "--url",
                        "ws://192.0.2.10:8765",
                        "--token-file",
                        str(token_file),
                        "--version",
                        "1",
                        "--ota-url",
                        "http://192.0.2.10:8765/ota",
                        "--output",
                        str(output),
                        "--size",
                        "4096",
                        "--generator",
                        str(generator),
                    ]
                )
            self.assertEqual(result, 0)
            self.assertFalse(token_file.exists())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertIn("no USB write was requested", stdout.getvalue())

    def test_cli_requires_explicit_write_and_a_port(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            main(
                [
                    "--url",
                    "ws://192.0.2.10:8765",
                    "--version",
                    "1",
                    "--ota-url",
                    "http://192.0.2.10:8765/ota",
                    "--output",
                    "unused.bin",
                    "--write",
                ]
            )
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
