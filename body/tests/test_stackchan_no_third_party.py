"""Exercise the no-third-party capture check with a sanitized destination list."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "stackchan-no-third-party.sh"
CAPTURE = Path(__file__).parent / "fixtures" / "stackchan" / "destinations-allowed.txt"


class StackChanNoThirdPartyTests(unittest.TestCase):
    def test_sample_capture_list_passes_and_unlisted_host_fails(self) -> None:
        allowed = subprocess.run(
            [
                "bash",
                str(SCRIPT),
                "--hosts",
                str(CAPTURE),
                "--hub",
                "192.0.2.10",
                "--router",
                "192.0.2.1",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(allowed.returncode, 0, allowed.stderr + allowed.stdout)
        self.assertIn("fit the local StackChan allowlist", allowed.stdout)

        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "destinations.txt"
            capture.write_text(CAPTURE.read_text(encoding="utf-8") + "203.0.113.42\n")
            rejected = subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--hosts",
                    str(capture),
                    "--hub",
                    "192.0.2.10",
                    "--router",
                    "192.0.2.1",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(rejected.returncode, 1, rejected.stderr + rejected.stdout)
        self.assertIn("203.0.113.42", rejected.stdout)
        self.assertIn("capture again", rejected.stdout)

    @staticmethod
    def scan(strings: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), "--strings", str(strings)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_strings_scan_flags_vendor_hosts_but_not_board_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            strings = Path(directory) / "strings.txt"
            strings.write_text(
                "M5StackCoreS3Board\nM5Stack-StackChan-Board\ncom.m5stack.stackchan\n"
            )
            ok = self.scan(strings)
            self.assertEqual(ok.returncode, 0, ok.stderr + ok.stdout)
            strings.write_text("https://api.m5stack.com/v1\n")
            bad = self.scan(strings)
            self.assertEqual(bad.returncode, 1, bad.stderr + bad.stdout)
            self.assertIn("m5stack.com", bad.stdout)


if __name__ == "__main__":
    unittest.main()
