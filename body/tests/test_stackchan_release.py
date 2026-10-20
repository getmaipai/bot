"""Release artifact and OTA policy checks for StackChan firmware."""

from __future__ import annotations

import hashlib
import json
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


def _write_signed_manifest(out: Path, image: Path) -> None:
    """A one-part manifest signed with a throwaway key, as release.sh writes it."""
    from maipai_body.bodies.stackchan.firmware import flash_manifest

    key = out.parent / f"{out.name}-key.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(key)],
        check=True,
        capture_output=True,
    )
    data = image.read_bytes()
    part = {
        "path": image.name,
        "offset": 0x20000,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    manifest = flash_manifest.build_manifest(
        [part],
        version="1.0.0",
        flash_size="16MB",
        created_at="2026-10-20T00:00:00Z",
        hlc="1792454400000:0:stackchan01",
    )
    signed = flash_manifest.sign_manifest(manifest, key)
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(key),
            "-pubout",
            "-out",
            str(out.parent / f"{out.name}-public.pem"),
        ],
        check=True,
        capture_output=True,
    )
    key.unlink()
    (out / "flash-manifest.json").write_text(json.dumps(signed, sort_keys=True, indent=2) + "\n")


class StackChanReleaseTests(unittest.TestCase):
    def run_script(self, script: Path, *args: str, env: dict[str, str] | None = None):
        return subprocess.run(["bash", str(script), *args], capture_output=True, text=True, env=env)

    def test_verify_rejects_a_tampered_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            image = out / "stack-chan-maipai.bin"
            image.write_bytes(b"test image")
            _write_signed_manifest(out, image)
            public_key = out.parent / f"{out.name}-public.pem"
            sums = ""
            for name in (image.name, "flash-manifest.json"):
                sums += f"{hashlib.sha256((out / name).read_bytes()).hexdigest()}  {name}\n"
            (out / "SHA256SUMS").write_text(sums)
            passed = self.run_script(VERIFY, "--public-key", str(public_key), str(out))
            self.assertEqual(passed.returncode, 0, passed.stderr + passed.stdout)
            image.write_bytes(b"tampered image")
            failed = self.run_script(VERIFY, "--public-key", str(public_key), str(out))
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("checksum", (failed.stderr + failed.stdout).lower())

    def test_verify_requires_and_checks_manifest_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            out = root / "release"
            out.mkdir()
            image = out / "image.bin"
            image.write_bytes(b"signed image")
            _write_signed_manifest(out, image)
            public_key = root / "release-public.pem"

            def sums() -> str:
                return "".join(
                    f"{hashlib.sha256((out / n).read_bytes()).hexdigest()}  {n}\n"
                    for n in ("image.bin", "flash-manifest.json")
                )

            (out / "SHA256SUMS").write_text(sums())
            ok = self.run_script(VERIFY, str(out), "--public-key", str(public_key))
            self.assertEqual(ok.returncode, 0, ok.stderr + ok.stdout)
            wrong = root / "wrong.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(wrong)],
                check=True,
                capture_output=True,
            )
            wrong_pub = root / "wrong-public.pem"
            subprocess.run(
                ["openssl", "pkey", "-in", str(wrong), "-pubout", "-out", str(wrong_pub)],
                check=True,
                capture_output=True,
            )
            bad = self.run_script(VERIFY, "--public-key", str(wrong_pub), str(out))
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("signature", (bad.stderr + bad.stdout).lower())
            omitted = self.run_script(VERIFY, str(out))
            self.assertEqual(omitted.returncode, 2)
            self.assertIn("--public-key", omitted.stderr)
            manifest = json.loads((out / "flash-manifest.json").read_text())
            manifest.pop("signature")
            (out / "flash-manifest.json").write_text(
                json.dumps(manifest, sort_keys=True, indent=2) + "\n"
            )
            (out / "SHA256SUMS").write_text(sums())
            unsigned = self.run_script(VERIFY, str(out), "--public-key", str(public_key))
            self.assertNotEqual(unsigned.returncode, 0)
            self.assertIn("not signed", (unsigned.stderr + unsigned.stdout).lower())

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
