"""Build and verify signed StackChan flash manifests."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from maipai_body.spec_pin import SPEC_CHECKOUT


def _spec_root() -> Path:
    configured = os.environ.get("MAIPAI_SPEC_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[5].parent / SPEC_CHECKOUT


def parts_from_flasher_args(build_dir: str | Path) -> list[dict[str, Any]]:
    """Read offsets from ESP-IDF metadata and hash the referenced build images."""
    build = Path(build_dir)
    metadata = json.loads((build / "flasher_args.json").read_text())
    files = metadata.get("flash_files")
    if not isinstance(files, dict):
        raise ValueError("flasher_args.json is missing flash_files")
    parts = []
    for raw_offset, relative in files.items():
        try:
            offset = int(raw_offset, 16)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid flash offset {raw_offset!r}") from exc
        source = (build / relative).resolve()
        if not source.is_relative_to(build.resolve()):
            raise ValueError(f"flash file escapes build directory: {relative}")
        if not source.is_file():
            raise ValueError(f"flash part {relative}: file is missing")
        data = source.read_bytes()
        parts.append(
            {
                "path": source.name,
                "offset": offset,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return sorted(parts, key=lambda part: part["offset"])


def build_manifest(
    parts: list[dict[str, Any]],
    *,
    version: str,
    flash_size: str,
    created_at: str,
    hlc: str,
    provenance: str = "BOT-RELEASE-FLASH-01",
) -> dict[str, Any]:
    return {
        "id": f"stackchan-esp32s3-{version}",
        "name": "StackChan",
        "version": version,
        "builds": [{"chipFamily": "ESP32-S3", "parts": parts}],
        "flash_size": flash_size,
        "provenance": provenance,
        "created_at": created_at,
        "hlc": hlc,
    }


def signing_payload(manifest: dict[str, Any]) -> bytes:
    root = _spec_root()
    sys.path.insert(0, str(root))
    try:
        from records.py.validate import firmware_flash_manifest_signing_payload

        return firmware_flash_manifest_signing_payload(manifest)
    finally:
        sys.path.pop(0)


def _openssl_public_key(key_path: str | Path) -> bytes:
    result = subprocess.run(
        ["openssl", "pkey", "-in", str(key_path), "-pubout", "-outform", "DER"],
        check=True,
        capture_output=True,
    )
    # SubjectPublicKeyInfo's final 32 bytes are the raw Ed25519 key.
    der = result.stdout
    if len(der) < 32:
        raise ValueError("OpenSSL returned an invalid Ed25519 public key")
    return der[-32:]


def sign_manifest(manifest: dict[str, Any], key_path: str | Path) -> dict[str, Any]:
    signed = json.loads(json.dumps(manifest))
    signed.pop("signature", None)
    raw_public = _openssl_public_key(key_path)
    payload_path = Path(os.environ.get("TMPDIR", "/tmp")) / f"stackchan-signing-{os.getpid()}.json"
    try:
        payload_path.write_bytes(signing_payload(signed))
        signature = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-rawin",
                "-inkey",
                str(key_path),
                "-in",
                str(payload_path),
            ],
            check=True,
            capture_output=True,
        ).stdout
    finally:
        payload_path.unlink(missing_ok=True)
    signed["signature"] = {
        "keyid": hashlib.sha256(raw_public).hexdigest()[:16],
        "sig": base64.b64encode(signature).decode("ascii"),
    }
    return signed


def verify_manifest(manifest: dict[str, Any], public_key_path: str | Path) -> bool:
    try:
        raw_public = subprocess.run(
            ["openssl", "pkey", "-pubin", "-in", str(public_key_path), "-outform", "DER"],
            check=True,
            capture_output=True,
        ).stdout[-32:]
        signature = manifest["signature"]
        if signature["keyid"] != hashlib.sha256(raw_public).hexdigest()[:16]:
            return False
        payload_path = (
            Path(os.environ.get("TMPDIR", "/tmp")) / f"stackchan-verify-{os.getpid()}.json"
        )
        sig_path = payload_path.with_suffix(".sig")
        try:
            payload_path.write_bytes(signing_payload(manifest))
            sig_path.write_bytes(base64.b64decode(signature["sig"], validate=True))
            result = subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-verify",
                    "-rawin",
                    "-pubin",
                    "-inkey",
                    str(public_key_path),
                    "-in",
                    str(payload_path),
                    "-sigfile",
                    str(sig_path),
                ],
                capture_output=True,
            )
            return result.returncode == 0
        finally:
            payload_path.unlink(missing_ok=True)
            sig_path.unlink(missing_ok=True)
    except (KeyError, ValueError, OSError, subprocess.CalledProcessError):
        return False


def validate_manifest(manifest: dict[str, Any], spec_root: str | Path | None = None) -> None:
    """Run the pinned JSON schema and record validator with useful part errors."""
    root = Path(spec_root) if spec_root else _spec_root()
    sys.path.insert(0, str(root))
    try:
        from gen.py.firmware_flash_manifest_schema import FirmwareFlashManifest
    except Exception as exc:
        raise ValueError(f"manifest validation failed: {exc}") from exc
    finally:
        sys.path.pop(0)
    sys.path.insert(0, str(root))
    try:
        from records.py.validate import validate_firmware_flash_manifest

        model = FirmwareFlashManifest.model_validate(manifest)
        problems = validate_firmware_flash_manifest(model)
    except Exception as exc:
        raise ValueError(f"manifest validation failed: {exc}") from exc
    finally:
        sys.path.pop(0)
    if problems:
        raise ValueError("manifest validation failed: " + "; ".join(problems))


def _created_at(day: str) -> str:
    return (
        datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _hlc(day: str) -> str:
    # From the build date, not the wall clock: a rebuild of one date yields the same manifest.
    midnight = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=UTC)
    return f"{int(midnight.timestamp() * 1000)}:0:stackchan01"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--build-dir", required=True)
    build.add_argument("--release-dir", required=True)
    build.add_argument("--version", required=True)
    build.add_argument("--date", required=True)
    build.add_argument("--key", required=True)
    build.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        metadata = json.loads((Path(args.build_dir) / "flasher_args.json").read_text())
        parts = parts_from_flasher_args(args.build_dir)
        chip = metadata.get("extra_esptool_args", {}).get("chip")
        if chip != "esp32s3":
            raise ValueError(f"expected ESP-IDF chip esp32s3, got {chip!r}")
        release = Path(args.release_dir)
        release.mkdir(parents=True, exist_ok=True)
        for part in parts:
            relative = next(
                path
                for offset, path in metadata["flash_files"].items()
                if int(offset, 16) == part["offset"]
            )
            source = Path(args.build_dir) / relative
            target = release / part["path"]
            if source.resolve() != target.resolve():
                target.write_bytes(source.read_bytes())
        settings = metadata.get("flash_settings", {})
        manifest = build_manifest(
            parts,
            version=args.version,
            flash_size=settings["flash_size"],
            created_at=_created_at(args.date),
            hlc=_hlc(args.date),
        )
        signed = sign_manifest(manifest, args.key)
        validate_manifest(signed)
        Path(args.out).write_text(json.dumps(signed, sort_keys=True, indent=2) + "\n")
    except Exception as exc:
        parser.exit(1, f"flash manifest error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
