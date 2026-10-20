from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from maipai_body.dashboard.server import DashboardServer

ROOT = Path(__file__).resolve().parents[1]


class StackChanSetupPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PairingStore(Path(self.temp.name) / "pairing.json")
        self.server = DashboardServer(
            FakeReachyMiniClient(),
            REACHY_MINI_PROFILE,
            host="127.0.0.1",
            port=0,
            pairing_store=self.store,
        )
        self.server.start()
        self.addCleanup(self.server.stop)
        self.device = "02:00:00:00:00:28"
        self.client = "00000000-0000-4000-8000-000000000028"
        self.store.request(self.device, self.client)

    def request(self, method: str, path: str, body: dict | None = None, origin: str | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port)
        headers = {"Origin": origin or f"http://127.0.0.1:{self.server.port}"}
        encoded = None
        if body is not None:
            encoded = json.dumps(body)
            headers["Content-Type"] = "application/json"
        connection.request(method, path, encoded, headers)
        response = connection.getresponse()
        result = response.read()
        status, content_type = response.status, response.getheader("Content-Type")
        connection.close()
        return status, content_type, result

    def test_pairing_page_lists_pending_and_approval_never_returns_token(self) -> None:
        status, content_type, page = self.request("GET", "/pairing")
        self.assertEqual((status, content_type), (200, "text/html; charset=utf-8"))
        self.assertIn(b"Device-Id", page)
        self.assertIn(b"Approve", page)
        self.assertIn(b"Refuse", page)
        status, _, payload = self.request(
            "POST",
            "/api/stackchan/pairings/approve",
            {"device_id": self.device, "client_id": self.client},
        )
        self.assertEqual(status, 200)
        approval = json.loads(payload)
        token = Path(approval["token_file"]).read_text().strip().encode()
        self.assertNotIn(token, payload)

    def test_cross_origin_pairing_change_is_refused(self) -> None:
        status, _, payload = self.request(
            "POST",
            "/api/stackchan/pairings/approve",
            {"device_id": self.device, "client_id": self.client},
            "http://evil.example",
        )
        self.assertEqual(status, 403)
        self.assertIn(b"cross-origin", payload)

    def test_refuse_removes_only_the_pending_request(self) -> None:
        status, _, payload = self.request(
            "POST",
            "/api/stackchan/pairings/refuse",
            {"device_id": self.device, "client_id": self.client},
        )
        self.assertEqual(status, 200)
        self.assertIn(b'"refused": true', payload)
        self.assertEqual(self.store.pending(), ())


class StackChanFlashDryRunTests(unittest.TestCase):
    def test_dry_run_lists_backup_before_write_and_requires_backup_file(self) -> None:
        script = ROOT / "scripts" / "stackchan_flash.py"
        self.assertTrue(script.is_file())
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            token = base / "approved.token"
            token.write_text("secret-demo-value\n")
            backup = base / "whole-flash.bin"
            args = [
                sys.executable,
                str(script),
                "--dry-run",
                "--port",
                "fake-port",
                "--backup",
                str(backup),
                "--token-file",
                str(token),
                "--device-id",
                "02:00:00:00:00:28",
                "--client-id",
                "00000000-0000-4000-8000-000000000028",
                "--xiaozhi-url",
                "ws://192.0.2.10:8765",
                "--avatar-url",
                "ws://192.0.2.10:8766",
            ]
            # An empty build root keeps the dry run off whatever build the machine left in ~/esp.
            env = {**os.environ, "STACKCHAN_BUILD_ROOT": str(base / "build")}
            result = subprocess.run(args, capture_output=True, text=True, check=False, env=env)
            self.assertEqual(result.returncode, 2)
            self.assertIn("backup", result.stderr.lower())
            with backup.open("wb") as stream:
                stream.truncate(16 * 1024 * 1024)
            result = subprocess.run(args, capture_output=True, text=True, check=False, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            self.assertLess(
                next(i for i, line in enumerate(lines) if "BACKUP" in line),
                next(i for i, line in enumerate(lines) if "FLASH" in line),
            )
            self.assertNotIn("secret-demo-value", result.stdout)


class StackChanFlashIdfEnvTests(unittest.TestCase):
    """Regression: on the first unit (2026-10-19) export.sh failed under `uv run`."""

    def setUp(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(sys.path.remove, str(ROOT / "scripts"))
        import stackchan_flash

        self.flash = stackchan_flash

    def test_bot_virtualenv_does_not_reach_esp_idf_export(self) -> None:
        seen = {}

        def fake_run(command, **kwargs):
            seen.update(kwargs["env"])
            return subprocess.CompletedProcess(command, 0, b"IDF_PATH=/idf\0PATH=/idf/bin\0", b"")

        venv = "/demo/body/.venv"
        environ = {"VIRTUAL_ENV": venv, "PATH": f"{venv}/bin:/usr/bin", "PYTHONPATH": "/x"}
        with (
            unittest.mock.patch.dict("os.environ", environ, clear=True),
            unittest.mock.patch.object(self.flash.subprocess, "run", fake_run),
        ):
            env = self.flash._idf_env()
        self.assertEqual(env["IDF_PATH"], "/idf")
        self.assertNotIn("VIRTUAL_ENV", seen)
        self.assertNotIn("PYTHONPATH", seen)
        self.assertEqual(seen["PATH"], "/usr/bin")

    def test_export_that_loads_nothing_stops_setup(self) -> None:
        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, b"PATH=/usr/bin\0", b"")

        with unittest.mock.patch.object(self.flash.subprocess, "run", fake_run):
            with self.assertRaisesRegex(ValueError, "ESP-IDF did not load"):
                self.flash._idf_env()

    def test_failed_step_never_prints_the_pairing_token(self) -> None:
        # Regression: a failed recipe step printed the token in "Setup stopped".
        command = ["false", "--pairing-token", "secret-demo-value"]
        with self.assertRaises(ValueError) as caught:
            self.flash._run(command, dry_run=False)
        self.assertNotIn("secret-demo-value", str(caught.exception))
        self.assertIn("<private-token>", str(caught.exception))

    def test_flash_writes_built_images_and_nvs_without_reconfiguring(self) -> None:
        # Regression: idf.py flash reconfigured after recipe.sh removed its private config.
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            _write_build_output(build)
            command = self.flash._write_flash_command("fake-port", build, build / "nvs.bin")
        self.assertNotIn("idf.py", command)
        self.assertEqual(command[command.index("write_flash") + 1], "--flash_mode")
        self.assertIn(str(build / "bootloader/bootloader.bin"), command)
        self.assertEqual(command[-2:], ["0x9000", str(build / "nvs.bin")])

    def test_flash_args_without_firmware_images_stops_before_writing(self) -> None:
        # Review finding: an options-only flash_args wrote NVS alone and reported DONE.
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            (build / "flash_args").write_text("--flash_mode dio\n0x9000 nvs-only.bin\n")
            (build / "nvs-only.bin").write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "no image at 0x0, 0x8000, 0x20000"):
                self.flash._write_flash_command("fake-port", build, build / "nvs.bin")

    def test_flash_args_naming_a_missing_image_stops_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            _write_build_output(build)
            (build / "maipai-stackchan.bin").unlink()
            with self.assertRaisesRegex(ValueError, "missing .*maipai-stackchan.bin"):
                self.flash._write_flash_command("fake-port", build, build / "nvs.bin")

    def test_flash_without_build_output_stops_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "Run setup again"):
                self.flash._write_flash_command("fake-port", Path(temp), Path(temp) / "nvs.bin")

    def _main_with_flash_result(self, base: Path, flash_fails: bool) -> tuple[int, Path]:
        build = base / "build"
        (build / "StackChan/firmware/build").mkdir(parents=True)
        _write_build_output(build / "StackChan/firmware/build")
        token = base / "approved.token"
        token.write_text("secret-demo-value\n")
        backup = base / "whole-flash.bin"
        with backup.open("wb") as stream:
            stream.truncate(16 * 1024 * 1024)

        def fake_run(command, *, dry_run, env=None):
            if "--token-file" in command:
                # provision.py deletes the token file it was given.
                Path(command[command.index("--token-file") + 1]).unlink()
            if "write_flash" in command and flash_fails:
                raise ValueError("This step failed with exit code 2")

        argv = ["stackchan_flash.py", "--port", "fake-port", "--backup", str(backup)]
        argv += ["--token-file", str(token), "--device-id", "02:00:00:00:00:28"]
        argv += ["--client-id", "00000000-0000-4000-8000-000000000028"]
        argv += ["--xiaozhi-url", "ws://192.0.2.10:8765", "--avatar-url", "ws://192.0.2.10:8766"]
        version = f"ESP-IDF v{self.flash._idf_version()}"
        with (
            unittest.mock.patch.object(sys, "argv", argv),
            unittest.mock.patch.object(self.flash, "BUILD_ROOT", build),
            unittest.mock.patch.object(self.flash, "_idf_env", lambda: {}),
            unittest.mock.patch.object(self.flash, "_run", fake_run),
            unittest.mock.patch.object(
                self.flash.subprocess, "check_output", lambda *a, **k: version
            ),
        ):
            return self.flash.main(), token

    def test_failed_flash_keeps_the_approved_token_for_a_retry(self) -> None:
        # Regression: provision deleted the token before the flash write failed.
        with tempfile.TemporaryDirectory() as temp:
            code, token = self._main_with_flash_result(Path(temp), flash_fails=True)
            self.assertEqual(code, 2)
            self.assertTrue(token.is_file())

    def test_successful_flash_removes_the_approved_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            code, token = self._main_with_flash_result(Path(temp), flash_fails=False)
            self.assertEqual(code, 0)
            self.assertFalse(token.is_file())


def _write_build_output(build: Path) -> None:
    """The five-line flash_args shape ESP-IDF writes for this firmware, with its images."""
    build.mkdir(parents=True, exist_ok=True)
    images = {
        "0x0": "bootloader/bootloader.bin",
        "0x8000": "partition_table/partition-table.bin",
        "0xd000": "ota_data_initial.bin",
        "0x20000": "maipai-stackchan.bin",
        "0xa00000": "generated_assets.bin",
    }
    lines = ["--flash_mode dio --flash_freq 80m --flash_size 16MB"]
    for offset, name in images.items():
        (build / name).parent.mkdir(parents=True, exist_ok=True)
        (build / name).write_bytes(b"x")
        lines.append(f"{offset} {name}")
    (build / "flash_args").write_text("\n".join(lines) + "\n")
