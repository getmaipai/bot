"""Tests for staging the independent StackChan firmware release asset."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "build-stackchan-firmware-asset.sh"


def _write_signed_manifest(
    out: Path, names: tuple[str, ...] = ("stack-chan-maipai.bin", "bootloader.bin")
) -> None:
    from maipai_body.bodies.stackchan.firmware import flash_manifest

    key = out.parent / f"{out.name}-key.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(key)],
        check=True,
        capture_output=True,
    )
    parts = []
    for index, name in enumerate(names):
        data = f"firmware part {index}".encode()
        (out / name).write_bytes(data)
        parts.append(
            {
                "path": name,
                "offset": index * 0x10000,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = flash_manifest.build_manifest(
        parts,
        version="1.2.3",
        flash_size="16MB",
        created_at="2026-10-20T00:00:00Z",
        hlc="1792454400000:0:stackchan01",
    )
    signed = flash_manifest.sign_manifest(manifest, key)
    key.unlink()
    (out / "flash-manifest.json").write_text(json.dumps(signed, sort_keys=True, indent=2) + "\n")


class StackChanFirmwareAssetTests(unittest.TestCase):
    def run_builder(self, tag: str, release: Path, stage: Path):
        env = os.environ.copy()
        env["MAIPAI_BOT_BUNDLE_OUT_DIR"] = str(stage)
        return subprocess.run(
            ["bash", str(SCRIPT), tag, str(release)], capture_output=True, text=True, env=env
        )

    def test_build_is_rooted_validated_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release, stage = root / "firmware", root / "stage"
            release.mkdir()
            _write_signed_manifest(release)
            result = self.run_builder("v1.2.3", release, stage)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            archive = stage / "stackchan-firmware-1.2.3.tar.gz"
            first = archive.read_bytes()
            with tarfile.open(archive, "r:gz") as tar:
                self.assertEqual(
                    tar.getnames(),
                    ["flash-manifest.json", "stack-chan-maipai.bin", "bootloader.bin"],
                )
                self.assertTrue(all(not name.startswith(("/", "./")) for name in tar.getnames()))
            expected = f"{hashlib.sha256(first).hexdigest()}  {archive.name}"
            self.assertEqual((stage / "SHA256SUMS").read_text().splitlines(), [expected])
            again = self.run_builder("v1.2.3", release, stage)
            self.assertEqual(again.returncode, 0, again.stderr + again.stdout)
            self.assertEqual(archive.read_bytes(), first)
            self.assertEqual((stage / "SHA256SUMS").read_text().splitlines(), [expected])

    def test_refuses_tampered_or_missing_part(self) -> None:
        for mutation in ("tampered", "missing"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                release, stage = root / "firmware", root / "stage"
                release.mkdir()
                _write_signed_manifest(release)
                part = release / "stack-chan-maipai.bin"
                if mutation == "tampered":
                    part.write_bytes(b"tampered part!!")
                else:
                    part.unlink()
                result = self.run_builder("v1.2.3", release, stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "sha256" if mutation == "tampered" else "missing",
                    (result.stderr + result.stdout).lower(),
                )

    def test_refuses_unsafe_part_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release, stage = root / "firmware", root / "stage"
            release.mkdir()
            _write_signed_manifest(release)
            manifest_path = release / "flash-manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["builds"][0]["parts"][0]["path"] = "../escape.bin"
            manifest_path.write_text(json.dumps(manifest))
            result = self.run_builder("v1.2.3", release, stage)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsafe path", (result.stderr + result.stdout).lower())

    def test_refuses_bad_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release, stage = root / "firmware", root / "stage"
            release.mkdir()
            result = self.run_builder("1.2.3", release, stage)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid release tag", (result.stderr + result.stdout).lower())


if __name__ == "__main__":
    unittest.main()
