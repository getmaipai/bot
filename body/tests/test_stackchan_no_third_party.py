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


if __name__ == "__main__":
    unittest.main()
