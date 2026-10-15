from __future__ import annotations

import http.client
import json
import subprocess
import sys
import tempfile
import unittest
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
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("backup", result.stderr.lower())
            with backup.open("wb") as stream:
                stream.truncate(16 * 1024 * 1024)
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            self.assertLess(
                next(i for i, line in enumerate(lines) if "BACKUP" in line),
                next(i for i, line in enumerate(lines) if "FLASH" in line),
            )
            self.assertNotIn("secret-demo-value", result.stdout)
