"""Release artifact and OTA policy checks for StackChan firmware."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
FIRMWARE = ROOT / "body" / "maipai_body" / "bodies" / "stackchan" / "firmware"
RELEASE = FIRMWARE / "release.sh"
VERIFY = FIRMWARE / "verify.sh"
VENDOR_SCAN = ROOT / "scripts" / "stackchan-no-third-party.sh"


class StackChanReleaseTests(unittest.TestCase):
    def run_script(self, script: Path, *args: str, env: dict[str, str] | None = None):
        return subprocess.run(["bash", str(script), *args], capture_output=True, text=True, env=env)

    def test_verify_rejects_a_tampered_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            image = out / "stack-chan-maipai.bin"
            image.write_bytes(b"test image")
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            (out / "SHA256SUMS").write_text(f"{digest}  {image.name}\n")
            passed = self.run_script(VERIFY, str(out))
            self.assertEqual(passed.returncode, 0, passed.stderr + passed.stdout)
            image.write_bytes(b"tampered image")
            failed = self.run_script(VERIFY, str(out))
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("checksum", (failed.stderr + failed.stdout).lower())

    def test_release_refuses_a_pin_without_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp)
            shutil.copy2(FIRMWARE / "pins.toml", fake / "pins.toml")
            # Checksum policy validation runs before Docker or any network access.
            result = self.run_script(RELEASE, "--check-pins", "--pins", str(fake / "pins.toml"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checksum", (result.stderr + result.stdout).lower())

    def test_vendor_host_scan_rejects_synthetic_image_strings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            strings = Path(temp) / "image-strings.txt"
            strings.write_text("safe.example\napi.tenclass.net\n")
            result = self.run_script(VENDOR_SCAN, "--strings", str(strings))
            self.assertEqual(result.returncode, 1)
            self.assertIn("tenclass", result.stdout)

    def test_ota_reply_never_offers_a_firmware_url(self) -> None:
        server = ROOT / "body" / "maipai_body" / "bodies" / "stackchan" / "xiaozhi" / "server.py"
        source = server.read_text()
        self.assertNotIn('"firmware"', source)
        self.assertNotIn('"firmware.url"', source)
