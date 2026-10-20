"""Offline fake-device protocol replay for StackChan xiaozhi."""

from __future__ import annotations

import ast
import asyncio
import concurrent.futures
import io
import json
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from aiohttp import ClientSession, FormData, web
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from maipai_body.bodies.stackchan.xiaozhi.provision import (
    _tool_python,
    generate_image,
    main,
    write_image,
)
from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient, XiaozhiServer


class StackChanXiaozhiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.pairing = PairingStore()
        self.client_id = "00000000-0000-4000-8000-000000000001"
        self.pairing.request("02:00:00:00:00:01", self.client_id)
        self.token = self.pairing.approve("02:00:00:00:00:01", self.client_id)
        self.stackchan_client = FakeStackChanDeviceClient()
        self.robot = StackChanRobotAdapter(self.stackchan_client)
        self.audio: list[tuple[str, bytes]] = []

        async def on_audio(session: str, frame: bytes) -> None:
            self.audio.append((session, frame))

        self.app = XiaozhiServer(
            self.pairing, self.robot, on_audio, vision_host="127.0.0.1", vision_port=8766
        )
        self.server = await serve(self.app.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        app = web.Application(client_max_size=self.app.max_photo_bytes)
        app.router.add_post("/vision/{device_id}", self.app._receive_photo)
        self.app._vision_runner = web.AppRunner(app)
        await self.app._vision_runner.setup()
        site = web.TCPSite(self.app._vision_runner, "127.0.0.1", self.app.vision_port)
        await site.start()
        self.app._vision_site = site
        self.vision_port = self.app.vision_port

    async def asyncTearDown(self) -> None:
        self.server.close()
        await self.server.wait_closed()
        if self.app._vision_runner is not None:
            await self.app._vision_runner.cleanup()

    async def device(self):
        return await connect(
            f"ws://127.0.0.1:{self.port}",
            additional_headers={
                "Device-Id": "02:00:00:00:00:01",
                "Client-Id": self.client_id,
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
            self.assertEqual(hello["version"], 1)
            self.assertEqual(hello["audio_params"]["sample_rate"], 24000)
            await ws.send(b"fake-opus-uplink")
            await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "manual"}))
            await ws.send(json.dumps({"type": "abort", "reason": "wake_word_detected"}))
            stopped = json.loads(await ws.recv())
            self.assertEqual(stopped["type"], "tts")
            await self.app.send_audio("02:00:00:00:00:01", [b"opus-frame-1", b"opus-frame-2"])
            start = json.loads(await ws.recv())
            self.assertEqual(start["state"], "start")
            self.assertIn("session_id", start)
            self.assertEqual(await ws.recv(), b"opus-frame-1")
            self.assertEqual(await ws.recv(), b"opus-frame-2")
            self.assertEqual(json.loads(await ws.recv())["state"], "stop")
        self.assertEqual(self.audio[0][1], b"fake-opus-uplink")

    async def test_initialize_advertises_authenticated_vision_url_and_token(self) -> None:
        from unittest.mock import AsyncMock

        ws = type("Socket", (), {"send": AsyncMock()})()
        self.app._sessions["02:00:00:00:00:01"] = ws
        self.app._session_credentials["02:00:00:00:00:01"] = (self.client_id, self.token)
        await self.app._mcp(ws, "session", {"id": 42, "method": "initialize"})
        payload = json.loads(ws.send.await_args.args[0])["payload"]["result"]
        self.assertEqual(payload["capabilities"]["vision"]["token"], self.token)
        self.assertEqual(
            payload["capabilities"]["vision"]["url"],
            f"http://127.0.0.1:{self.vision_port}/vision/02:00:00:00:00:01",
        )

    async def test_photo_upload_is_token_checked_bounded_and_memory_only(self) -> None:

        self.app._session_credentials["02:00:00:00:00:01"] = (self.client_id, self.token)
        url = f"http://127.0.0.1:{self.vision_port}/vision/02:00:00:00:00:01"
        async with ClientSession() as client:
            form = FormData()
            form.add_field(
                "image", b"\xff\xd8photo", filename="frame.jpg", content_type="image/jpeg"
            )
            accepted = await client.post(
                url, data=form, headers={"Authorization": f"Bearer {self.token}"}
            )
            self.assertEqual(accepted.status, 200)
            self.assertEqual(self.app._photos.pop("02:00:00:00:00:01"), b"\xff\xd8photo")

            form = FormData()
            form.add_field(
                "image", b"\xff\xd8photo", filename="frame.jpg", content_type="image/jpeg"
            )
            rejected = await client.post(url, data=form, headers={"Authorization": "Bearer wrong"})
            self.assertEqual(rejected.status, 403)

            self.app.max_photo_bytes = 32
            form = FormData()
            form.add_field(
                "image", b"\xff\xd8" + b"x" * 40, filename="large.jpg", content_type="image/jpeg"
            )
            oversized = await client.post(
                url, data=form, headers={"Authorization": f"Bearer {self.token}"}
            )
            self.assertEqual(oversized.status, 413)
            self.assertNotIn("02:00:00:00:00:01", self.app._photos)

    async def test_early_device_replies_keep_only_the_newest_32_inflight_calls(self) -> None:
        deadline = time.monotonic() + 10
        for request_id in range(1, 41):
            key = str(request_id)
            self.app._device_call_deadlines[key] = deadline
            await self.app._mcp(
                None,
                "session",
                {"jsonrpc": "2.0", "id": request_id, "result": {"value": request_id}},
            )

        self.assertEqual(len(self.app._early_device_replies), 32)
        self.assertNotIn("8", self.app._early_device_replies)
        self.assertIn("9", self.app._early_device_replies)
        self.assertIn("40", self.app._early_device_replies)

    async def test_expired_and_late_device_replies_are_discarded(self) -> None:
        self.app._device_call_deadlines["10"] = time.monotonic() - 1
        self.app._early_device_replies["10"] = {"result": {"stale": True}}
        self.app._device_call_deadlines["11"] = time.monotonic() + 10
        future = asyncio.get_running_loop().create_future()
        self.app._pending_device_calls["11"] = (future, "tool", "02:00:00:00:00:01")

        await self.app._mcp(
            None,
            "session",
            {"jsonrpc": "2.0", "id": 12, "result": {"unasked": True}},
        )
        self.assertNotIn("10", self.app._early_device_replies)
        self.assertNotIn("12", self.app._early_device_replies)

        with self.assertRaises(TimeoutError):
            await self.app._await_device_reply("11", "02:00:00:00:00:01", "tool", timeout=0.001)
        await self.app._mcp(
            None,
            "session",
            {"jsonrpc": "2.0", "id": 11, "result": {"late": True}},
        )
        self.assertNotIn("11", self.app._early_device_replies)

    async def test_reconnect_replaces_the_active_session_for_same_device_id(self) -> None:
        first = await self.device()
        await first.send(json.dumps({"type": "hello", "version": 1}))
        first_hello = json.loads(await first.recv())

        async def slow_stale_close(_stale) -> None:
            await asyncio.sleep(0.4)

        with patch.object(self.app, "_close_stale_session", new=slow_stale_close):
            second = await self.device()
            try:
                await second.send(json.dumps({"type": "hello", "version": 1}))
                replacement = json.loads(await asyncio.wait_for(second.recv(), timeout=0.2))
                self.assertEqual(replacement["type"], "hello")
                self.assertEqual(replacement["version"], 1)
                self.assertNotEqual(first_hello["session_id"], replacement["session_id"])
                self.assertEqual(len(self.app._sessions), 1)
                self.assertEqual(
                    self.app._session_ids["02:00:00:00:00:01"], replacement["session_id"]
                )
            finally:
                await second.close()
                await first.close()
                await asyncio.sleep(0.41)

    async def test_unknown_device_is_refused_and_queued_for_approval(self) -> None:
        async with connect(
            f"ws://127.0.0.1:{self.port}",
            additional_headers={
                "Device-Id": "02:00:00:00:00:02",
                "Client-Id": "00000000-0000-4000-8000-000000000002",
            },
        ) as ws:
            with self.assertRaises(Exception) as caught:
                await ws.recv()
            self.assertIn("approve this Device-Id in the dashboard", str(caught.exception))
        self.assertEqual(self.pairing.pending()[0].device_id, "02:00:00:00:00:02")

    async def test_pairing_token_is_bound_to_client_id(self) -> None:
        self.assertFalse(
            self.pairing.authorize(
                "02:00:00:00:00:01", "00000000-0000-4000-8000-000000000002", self.token
            )
        )

    async def test_approved_at_records_approval_time_not_request_time(self) -> None:
        device_id = "02:00:00:00:00:43"
        client_id = "00000000-0000-4000-8000-000000000043"
        with patch("maipai_body.bodies.stackchan.xiaozhi.pairing.time.time", return_value=100.0):
            self.pairing.request(device_id, client_id)
        with patch("maipai_body.bodies.stackchan.xiaozhi.pairing.time.time", return_value=145.0):
            self.pairing.approve(device_id, client_id)
        self.assertEqual(self.pairing._devices[device_id]["approved_at"], 145.0)

    async def test_pending_pairing_approval_requires_the_matching_client_id(self) -> None:
        device_id = "02:00:00:00:00:44"
        planted_client = "00000000-0000-4000-8000-000000000044"
        robot_client = "00000000-0000-4000-8000-000000000045"
        self.pairing.request(device_id, planted_client)
        self.pairing.request(device_id, robot_client)

        self.assertEqual(
            {(row.device_id, row.client_id) for row in self.pairing.pending()},
            {(device_id, planted_client), (device_id, robot_client)},
        )
        with self.assertRaisesRegex(KeyError, "Device-Id and Client-Id"):
            self.pairing.approve(device_id, "00000000-0000-4000-8000-000000000046")

        token = self.pairing.approve(device_id, robot_client)
        self.assertTrue(self.pairing.authorize(device_id, robot_client, token))
        self.assertFalse(self.pairing.authorize(device_id, planted_client, token))

    async def test_pairing_authorize_does_not_take_the_cross_process_write_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pairing.json"
            store = PairingStore(path)
            device_id = "02:00:00:00:00:46"
            client_id = "00000000-0000-4000-8000-000000000046"
            store.request(device_id, client_id)
            token = store.approve(device_id, client_id)
            import maipai_body.bodies.stackchan.xiaozhi.pairing as pairing_module

            with patch.object(
                pairing_module.fcntl,
                "flock",
                side_effect=AssertionError("read locked"),
            ):
                for _ in range(12):
                    self.assertTrue(store.authorize(device_id, client_id, token))

    async def test_separate_pairing_stores_refresh_shared_pending_approval_and_revocation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pairing.json"
            service = PairingStore(path)
            dashboard = PairingStore(path)
            device_id = "02:00:00:00:00:42"
            client_id = "00000000-0000-4000-8000-000000000042"

            request = service.request(device_id, client_id)
            self.assertEqual(dashboard.pending(), (request,))
            token_path = dashboard.approve_to_file(device_id, client_id)
            token = token_path.read_text(encoding="utf-8").strip()
            self.assertTrue(service.authorize(device_id, client_id, token))

            self.assertTrue(dashboard.revoke(device_id))
            self.assertFalse(service.authorize(device_id, client_id, token))
            token_path.unlink()

    async def test_pairing_persists_only_token_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "pairing.json"
            store = PairingStore(path)
            client_id = "00000000-0000-4000-8000-000000000003"
            store.request("02:00:00:00:00:03", client_id)
            token = store.approve("02:00:00:00:00:03", client_id)
            loaded = PairingStore(path)
            self.assertTrue(loaded.authorize("02:00:00:00:00:03", client_id, token))
            self.assertNotIn(token, path.read_text())

    async def test_audio_prebuffers_then_paces_from_monotonic_deadlines(self) -> None:
        now = [10.0]
        sent: list[tuple[bytes, float]] = []

        class WebSocket:
            async def send(self, payload):
                if not isinstance(payload, bytes):
                    return
                sent.append((payload, now[0]))
                now[0] += 0.025

        websocket = WebSocket()
        device_id = "02:00:00:00:00:01"
        self.app._sessions[device_id] = websocket
        self.app._session_ids[device_id] = "session"
        self.app._session_credentials[device_id] = (self.client_id, self.token)

        async def advance_sleep(delay: float) -> None:
            now[0] += delay

        with (
            patch(
                "maipai_body.bodies.stackchan.xiaozhi.server.time.monotonic",
                side_effect=lambda: now[0],
            ),
            patch(
                "maipai_body.bodies.stackchan.xiaozhi.server.asyncio.sleep",
                side_effect=advance_sleep,
            ),
        ):
            await self.app.send_audio(device_id, [f"frame-{i}".encode() for i in range(7)])

        self.assertEqual([frame for frame, _ in sent], [f"frame-{i}".encode() for i in range(7)])
        stamps = [stamp for _, stamp in sent]
        self.assertEqual([round(stamps[i + 1] - stamps[i], 3) for i in range(2)], [0.025, 0.025])
        self.assertAlmostEqual(stamps[3] - stamps[2], 0.085)
        self.assertAlmostEqual(stamps[6] - stamps[5], 0.06)

    async def test_corrupt_pairing_file_fails_closed_without_crashing_authorize(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "pairing.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertLogs(
                "maipai_body.bodies.stackchan.xiaozhi.pairing", level="ERROR"
            ) as logs:
                store = PairingStore(path)
                self.assertFalse(
                    store.authorize(
                        "02:00:00:00:00:03",
                        "00000000-0000-4000-8000-000000000003",
                        "token",
                    )
                )
            self.assertIn("Move it aside and reapprove devices", logs.output[0])

    async def test_pending_pairings_are_bounded_and_expire_after_ten_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = PairingStore(Path(temp) / "pairing.json")
            for index in range(8):
                store.request(
                    f"02:00:00:00:01:{index:02x}",
                    f"00000000-0000-4000-8000-{index:012x}",
                )
            with self.assertRaisesRegex(ValueError, "pending pairing list is full"):
                store.request("02:00:00:00:02:00", "00000000-0000-4000-8000-000000000100")
            import maipai_body.bodies.stackchan.xiaozhi.pairing as pairing_module

            with patch.object(pairing_module.time, "time", return_value=2_000_000_000):
                self.assertEqual(store.pending(), ())

    async def test_unauthenticated_pairing_requests_are_rate_limited_per_source(self) -> None:
        for _ in range(8):
            self.assertTrue(self.app._allow_pairing_request("192.0.2.8"))
        self.assertFalse(self.app._allow_pairing_request("192.0.2.8"))
        self.assertTrue(self.app._allow_pairing_request("192.0.2.9"))

    async def test_cancelled_device_call_surfaces_estop_engaged(self) -> None:
        from maipai_body.hal.errors import EstopEngaged

        class CallServer:
            def call_device_tool(self, *_args, **_kwargs):
                raise concurrent.futures.CancelledError()

            def cancel_device_calls(self, _name):
                return None

        with self.assertRaises(EstopEngaged):
            XiaozhiDeviceClient(CallServer()).set_head_angles(1, 2, 150)


class ProvisioningTests(unittest.TestCase):
    def test_generator_uses_the_esp_idf_python_environment(self) -> None:
        # Regression: on the first unit the NVS generator ran under the Bot's Python,
        # which lacks ESP-IDF's generator module; export.sh names the right one.
        with tempfile.TemporaryDirectory() as temp:
            python = Path(temp) / "bin" / "python"
            python.parent.mkdir()
            python.write_text("")
            with patch.dict("os.environ", {"IDF_PYTHON_ENV_PATH": temp}):
                self.assertEqual(_tool_python("/elsewhere/nvs_partition_gen.py"), str(python))

    def test_provisioning_image_uses_firmware_namespaces_and_integer_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_generator = root / "generator.py"
            fake_generator.write_text(
                "import csv, pathlib, sys\n"
                "rows = list(csv.reader(open(sys.argv[2], newline='')))\n"
                "pathlib.Path(sys.argv[3] + '.csv').write_text(repr(rows))\n"
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
            rows = ast.literal_eval(output.with_suffix(".bin.csv").read_text())
            self.assertEqual(rows[1], ["websocket", "namespace", "", ""])
            self.assertEqual(rows[4], ["version", "data", "i32", "1"])
            self.assertEqual(rows[5], ["wifi", "namespace", "", ""])
            self.assertEqual(rows[6], ["ota_url", "data", "string", "http://192.0.2.10:8765/ota"])
            called: list[list[str]] = []

            def fake_run(command, **kwargs):
                called.append(command)
                return type("Result", (), {"returncode": 0})()

            with patch("maipai_body.bodies.stackchan.xiaozhi.provision.subprocess.run", fake_run):
                write_image(output, port="/dev/fake-usb", esptool="esptool.py")
            self.assertIn("write_flash", called[0])
            self.assertIn("/dev/fake-usb", called[0])

    def test_provisioning_image_omits_empty_ota_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_generator = root / "generator.py"
            fake_generator.write_text(
                "import csv, pathlib, sys\n"
                "rows = list(csv.reader(open(sys.argv[2], newline='')))\n"
                "pathlib.Path(sys.argv[3] + '.csv').write_text(repr(rows))\n"
                "pathlib.Path(sys.argv[3]).write_bytes(b'x' * int(sys.argv[4], 0))\n"
            )
            output = generate_image(
                root / "nvs.bin",
                websocket_url="ws://192.0.2.10:8765",
                token="unit-token",
                version="1",
                ota_url="",
                partition_size=4096,
                generator=str(fake_generator),
            )
            rows = ast.literal_eval(output.with_suffix(".bin.csv").read_text())
            self.assertFalse(any(row[0] == "wifi" or row[0] == "ota_url" for row in rows[1:]))
            self.assertFalse(any(row[0] == "board" for row in rows[1:]))

    def test_real_esp_idf_generator_writes_namespaced_values(self) -> None:
        python_env = Path.home() / ".espressif/python_env/idf5.5_py3.12_env"
        python = python_env / "bin/python"
        generator = (
            python_env
            / "lib/python3.12/site-packages/esp_idf_nvs_partition_gen/nvs_partition_gen.py"
        )
        tool = Path.home() / "esp/esp-idf/components/nvs_flash/nvs_partition_tool/nvs_tool.py"
        if not python.is_file() or not generator.is_file() or not tool.is_file():
            self.skipTest("ESP-IDF NVS tools are unavailable; install ESP-IDF 5.5 tools and retry")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = generate_image(
                root / "nvs.bin",
                websocket_url="ws://192.0.2.10:8765",
                token="unit-token",
                version="1",
                ota_url="http://192.0.2.10:8765/ota",
                client_id="00000000-0000-4000-8000-000000000028",
                generator=str(generator),
            )
            dump = (
                subprocess.run(
                    [str(python), str(tool), str(image), "--dump", "minimal"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                .stdout.replace("\x00", "")
                .replace(" ", "")
            )
            for entry in (
                "websocket:url=ws://192.0.2.10:8765",
                "websocket:token=unit-token",
                "websocket:version=1",
                "wifi:ota_url=http://192.0.2.10:8765/ota",
                # The unit's Client-Id comes from board:uuid; found on the bench 2026-10-19.
                "board:uuid=00000000-0000-4000-8000-000000000028",
            ):
                self.assertIn(entry, dump)

    def test_cli_saves_private_no_write_image_then_consumes_one_time_token_file(self) -> None:
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
            self.assertTrue(output.is_file())
            self.assertIn("no USB write was requested", stdout.getvalue())

    def test_cli_keeps_token_file_when_usb_write_fails(self) -> None:
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
            with patch(
                "maipai_body.bodies.stackchan.xiaozhi.provision.write_image",
                side_effect=RuntimeError("USB NVS write failed on /dev/fake-usb."),
            ):
                with self.assertRaises(SystemExit):
                    main(
                        [
                            "--url",
                            "ws://192.0.2.10:8765",
                            "--token-file",
                            str(token_file),
                            "--version",
                            "1",
                            "--output",
                            str(root / "nvs.bin"),
                            "--size",
                            "4096",
                            "--generator",
                            str(generator),
                            "--write",
                            "--port",
                            "/dev/fake-usb",
                        ]
                    )
            self.assertTrue(token_file.exists())

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


class StackChanDefaultPortTests(unittest.TestCase):
    def test_vision_and_avatar_listeners_default_to_different_ports(self) -> None:
        # Both defaulted to 8766 on the same host; found on the bench 2026-10-19.
        import inspect

        from maipai_body.bodies.stackchan.avatar.server import AvatarServer
        from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer

        vision = inspect.signature(XiaozhiServer.__init__).parameters["vision_port"].default
        avatar = inspect.signature(AvatarServer.start).parameters["port"].default
        self.assertNotEqual(vision, avatar)
        app_source = Path(__file__).parents[1].joinpath("maipai_body/app.py").read_text()
        self.assertIn('"MAIPAI_VISION_PORT", "8767"', app_source)
        self.assertIn('"MAIPAI_STACKCHAN_AVATAR_PORT", "8766"', app_source)


if __name__ == "__main__":
    unittest.main()
