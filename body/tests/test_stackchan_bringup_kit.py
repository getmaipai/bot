from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from websockets.asyncio.server import serve

ROOT = Path(__file__).resolve().parents[2]
RECORDER = ROOT / "body/scripts/record_stackchan_fixtures.py"
EGRESS = ROOT / "scripts/stackchan-egress-proof.sh"


class BringupRecorderTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_unit_is_refused(self):
        result = subprocess.run(
            [sys.executable, str(RECORDER)], capture_output=True, text=True, check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--unit", result.stderr)

    async def test_fake_paired_peer_records_and_redacts_protocol_exchanges(self):
        ota_requests: list[dict] = []

        class OtaHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                ota_requests.append(json.loads(body))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"firmware":{"url":""}}')

            def log_message(self, format, *args):
                pass

        ota_server = ThreadingHTTPServer(("127.0.0.1", 0), OtaHandler)
        ota_thread = threading.Thread(target=ota_server.serve_forever, daemon=True)
        ota_thread.start()

        async def handler(ws):
            hello = json.loads(await ws.recv())
            await ws.send(json.dumps({"type": "hello", "session_id": "secret-session"}))
            request = json.loads(await ws.recv())
            self.assertEqual(request["payload"]["method"], "tools/list")
            await ws.send(
                json.dumps(
                    {
                        "type": "mcp",
                        "payload": {
                            "jsonrpc": "2.0",
                            "id": request["payload"]["id"],
                            "result": {"tools": [{"name": "self.camera.take_photo"}]},
                        },
                    }
                )
            )
            self.assertEqual(hello["type"], "hello")

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "capture.json"
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(RECORDER),
                    "--unit",
                    f"ws://127.0.0.1:{port}",
                    "--token",
                    "secret-token",
                    "--device-id",
                    "02:00:00:00:00:42",
                    "--client-id",
                    "00000000-0000-4000-8000-000000000042",
                    "--ota-url",
                    f"http://127.0.0.1:{ota_server.server_port}/ota",
                    "--output",
                    str(target),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=4)
                self.assertEqual(process.returncode, 0, (stdout + stderr).decode())
                payload = json.loads(target.read_text())
                serialized = target.read_text()
                self.assertEqual(
                    payload["tools_list"]["result"]["tools"][0]["name"], "self.camera.take_photo"
                )
                self.assertEqual(payload["ota"]["response"]["body"]["firmware"]["url"], "")
                self.assertEqual(ota_requests[0]["version"], 1)
                for secret in (
                    "secret-token",
                    "secret-session",
                    "02:00:00:00:00:42",
                    "00000000-0000-4000-8000-000000000042",
                ):
                    self.assertNotIn(secret, serialized)
                self.assertEqual(payload["ota"]["request"]["url"], "<REDACTED_URL>")
        ota_server.shutdown()
        ota_thread.join(timeout=1)
        ota_server.server_close()


class EgressProofTests(unittest.TestCase):
    def run_proof(self, contents: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "destinations.txt"
            capture.write_text(contents)
            return subprocess.run(
                ["bash", str(EGRESS), str(capture), "192.0.2.10"],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_host_only_capture_passes(self):
        result = self.run_proof("192.0.2.10\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_other_destination_is_reported_and_fails(self):
        result = self.run_proof("192.0.2.10\n192.0.2.99\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("192.0.2.99", result.stdout)


if __name__ == "__main__":
    unittest.main()
