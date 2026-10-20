"""Tests for release checksum signing and the Keychain key resolver."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
SIGN = ROOT / "scripts" / "sign-release-sums.sh"
RESOLVER = ROOT / "scripts" / "signing-key.sh"


class ReleaseSumsSigningTests(unittest.TestCase):
    def run_signer(self, key: str, stage: Path, env: dict[str, str]):
        return subprocess.run(
            ["bash", str(SIGN), "--signing-key", key, str(stage)],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_keychain_hex_and_plain_file_sign_and_clean_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = root / "stage"
            stage.mkdir()
            sums = b"0123456789abcdef  image.bin\n"
            (stage / "SHA256SUMS").write_bytes(sums)
            key = root / "key.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(key)],
                check=True,
                capture_output=True,
            )
            pub = root / "pub.pem"
            subprocess.run(
                ["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(pub)],
                check=True,
                capture_output=True,
            )
            pem = key.read_bytes()
            hex_secret = pem.hex()
            fake = root / "security"
            fake.write_text("#!/bin/sh\nprintf '%s\\n' '" + hex_secret + "'\n")
            fake.chmod(0o700)
            tmp = root / "tmp"
            tmp.mkdir()
            env = {**os.environ, "MAIPAI_SECURITY_BIN": str(fake), "TMPDIR": str(tmp)}
            result = self.run_signer("keychain:test-item", stage, env)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(list(tmp.iterdir()), [])
            self.assertNotIn(pem.decode(), result.stdout + result.stderr)
            self.assertNotIn(hex_secret, result.stdout + result.stderr)
            sigdoc = json.loads((stage / "SHA256SUMS.sig.json").read_text())
            signed_bytes = json.dumps(
                sigdoc["signed"], sort_keys=True, separators=(",", ":")
            ).encode()
            self.assertEqual(sigdoc["signed"]["sha256"], hashlib.sha256(sums).hexdigest())
            pub_der = subprocess.check_output(
                ["openssl", "pkey", "-pubin", "-in", str(pub), "-outform", "DER"]
            )
            self.assertEqual(
                sigdoc["signatures"][0]["keyid"], hashlib.sha256(pub_der[-32:]).hexdigest()[:16]
            )
            signature = base64.b64decode(sigdoc["signatures"][0]["sig"])
            payload = root / "payload.json"
            payload.write_bytes(signed_bytes)
            sig = root / "signature.bin"
            sig.write_bytes(signature)
            verified = subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-verify",
                    "-rawin",
                    "-pubin",
                    "-inkey",
                    str(pub),
                    "-in",
                    str(payload),
                    "-sigfile",
                    str(sig),
                ],
                capture_output=True,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr.decode())
            result = self.run_signer(str(key), stage, env)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_keychain_failure_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = root / "stage"
            stage.mkdir()
            (stage / "SHA256SUMS").write_text("x\n")
            fake = root / "security-fail"
            fake.write_text("#!/bin/sh\nexit 44\n")
            fake.chmod(0o700)
            result = self.run_signer(
                "keychain:test-item",
                stage,
                {**os.environ, "MAIPAI_SECURITY_BIN": str(fake), "TMPDIR": str(root)},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Keychain", result.stderr)
            self.assertEqual([p.name for p in root.iterdir() if p.name.startswith("maipai-")], [])

    def test_keychain_key_is_removed_when_a_later_release_step_fails(self) -> None:
        # release.sh resolves the key, then runs a long build;
        # a failed build must not leave the key behind.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            key = root / "key.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(key)],
                check=True,
                capture_output=True,
            )
            fake = root / "security"
            fake.write_text("#!/bin/sh\nprintf '%s\\n' '" + key.read_bytes().hex() + "'\n")
            fake.chmod(0o700)
            key.unlink()
            tmp = root / "tmp"
            tmp.mkdir()
            script = (
                f'set -euo pipefail; source "{RESOLVER}"; '
                'resolve_signing_key keychain:test-item; test -s "$SIGNING_KEY_PATH"; false'
            )
            env = {**os.environ, "MAIPAI_SECURITY_BIN": str(fake), "TMPDIR": str(tmp)}
            result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(list(tmp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
