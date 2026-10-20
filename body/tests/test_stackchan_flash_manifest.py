import json
import subprocess
import sys
from pathlib import Path

import pytest

from maipai_body.bodies.stackchan.firmware import flash_manifest

ROOT = Path(__file__).resolve().parents[1]
SPEC = flash_manifest._spec_root()
OFFSETS = [0x0, 0x8000, 0xD000, 0x20000, 0x340000]
NAMES = [
    "bootloader.bin",
    "partition-table.bin",
    "ota_data_initial.bin",
    "stack-chan-maipai.bin",
    "generated_assets.bin",
]


def _build(tmp_path):
    build = tmp_path / "build"
    release = tmp_path / "release"
    build.mkdir()
    release.mkdir()
    rows = {}
    for i, (offset, name) in enumerate(zip(OFFSETS, NAMES, strict=True)):
        data = bytes([i + 1]) * (20 + i)
        (build / name).write_bytes(data)
        (release / name).write_bytes(data)
        rows[hex(offset)] = name
    (build / "flasher_args.json").write_text(
        json.dumps(
            {
                "flash_files": rows,
                "flash_settings": {"flash_size": "16MB"},
                "extra_esptool_args": {"chip": "esp32s3"},
            }
        )
    )
    return build, release


def _key(tmp_path):
    path = tmp_path / "ed25519.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(path)],
        check=True,
        capture_output=True,
    )
    public = tmp_path / "ed25519.pub"
    with public.open("wb") as stream:
        subprocess.run(
            ["openssl", "pkey", "-in", str(path), "-pubout"],
            check=True,
            stdout=stream,
            stderr=subprocess.PIPE,
        )
    return path, public


def _manifest(tmp_path):
    build, release = _build(tmp_path)
    parts = flash_manifest.parts_from_flasher_args(build)
    manifest = flash_manifest.build_manifest(
        parts,
        version="1.0.0",
        flash_size="16MB",
        created_at="2026-10-20T12:00:00Z",
        hlc="1792497600000:0:stackchan01",
    )
    return build, release, manifest


def test_parts_come_from_flasher_args_with_file_sizes_and_hashes(tmp_path):
    build, release = _build(tmp_path)
    parts = flash_manifest.parts_from_flasher_args(build)
    assert [part["offset"] for part in parts] == OFFSETS
    for part in parts:
        data = (build / part["path"]).read_bytes()
        assert part["size"] == len(data)
        assert part["sha256"] == __import__("hashlib").sha256(data).hexdigest()
        assert (release / part["path"]).exists()


def test_manifest_validates_and_rejects_overlap_or_flash_overflow(tmp_path):
    _, _, unsigned = _manifest(tmp_path)
    manifest = flash_manifest.sign_manifest(unsigned, _key(tmp_path)[0])
    flash_manifest.validate_manifest(manifest, SPEC)
    overlap = json.loads(json.dumps(manifest))
    overlap["builds"][0]["parts"][1]["offset"] = 1
    with pytest.raises(ValueError, match="overlap"):
        flash_manifest.validate_manifest(overlap, SPEC)
    overflow = json.loads(json.dumps(manifest))
    overflow["builds"][0]["parts"][-1]["offset"] = 16 * 1024 * 1024
    with pytest.raises(ValueError, match="flash_size"):
        flash_manifest.validate_manifest(overflow, SPEC)


def test_sign_verify_and_part_tamper_detection(tmp_path):
    _, _, manifest = _manifest(tmp_path)
    private, public = _key(tmp_path)
    signed = flash_manifest.sign_manifest(manifest, private)
    assert flash_manifest.verify_manifest(signed, public)
    tampered = json.loads(json.dumps(signed))
    tampered["builds"][0]["parts"][0]["size"] += 1
    assert not flash_manifest.verify_manifest(tampered, public)


def test_signature_payload_matches_pinned_spec_helper(tmp_path):
    _, _, manifest = _manifest(tmp_path)
    sys.path.insert(0, str(SPEC))
    try:
        from records.py.validate import firmware_flash_manifest_signing_payload

        payload = flash_manifest.signing_payload(manifest)
        assert payload == firmware_flash_manifest_signing_payload(manifest)
    finally:
        sys.path.pop(0)


def test_release_requires_signing_key_before_build():
    script = ROOT / "maipai_body/bodies/stackchan/firmware/release.sh"
    run = subprocess.run(
        ["bash", str(script), "--date", "2026-10-20"], cwd=ROOT, text=True, capture_output=True
    )
    assert run.returncode != 0
    assert "--signing-key" in run.stderr
