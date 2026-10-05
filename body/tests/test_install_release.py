"""Release preparation and SSH plan stay local and reviewable."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPTS = ROOT / "scripts"


def test_install_dry_run_prints_the_full_plan_without_a_wheel_or_ssh():
    result = subprocess.run(
        [str(SCRIPTS / "install-reachy.sh"), "--dry-run", "example-host", "/tmp/future.whl"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "scp /tmp/future.whl pollen@example-host:/tmp/future.whl" in result.stdout
    assert "onnxruntime==1.30.0" in result.stdout
    assert "startup-app" in result.stdout
    assert "REMOVE_VENDOR_APPS" in result.stdout
    assert "systemctl restart reachy-mini-daemon" in result.stdout
    assert "rm\\ -f\\ \\'/tmp/future.whl\\'" in result.stdout


def test_release_builder_stages_wheel_and_sha256_without_publishing(tmp_path):
    stage = ROOT / "dist/bot-release/v0.1.0"
    try:
        subprocess.run([str(SCRIPTS / "prepare-bot-release.sh"), "v0.1.0"], check=True)
        wheel = stage / "maipai_bot-0.1.0-py3-none-any.whl"
        checksum = stage / f"{wheel.name}.sha256"
        assert wheel.is_file()
        assert checksum.read_text().split()[0] == hashlib.sha256(wheel.read_bytes()).hexdigest()
        assert "never creates" in (SCRIPTS / "prepare-bot-release.sh").read_text()
    finally:
        if stage.exists():
            for path in stage.iterdir():
                path.unlink()
            stage.rmdir()


def test_aarch64_voice_resolution_pins_onnxruntime_and_base_avoids_mujoco(tmp_path):
    results = {}
    for label, extra in (("base", []), ("voice", ["--extra", "voice"])):
        out = tmp_path / f"{label}.txt"
        result = subprocess.run(
            [
                "uv",
                "pip",
                "compile",
                "--python-platform",
                "aarch64-unknown-linux-gnu",
                "pyproject.toml",
                *extra,
                "-o",
                str(out),
            ],
            cwd=ROOT / "body",
            capture_output=True,
            text=True,
        )
        # The full resolver currently cannot build the transitive pygobject
        # dependency on macOS without cairo/pkg-config. Preserve a clear
        # skip so Linux CI can establish this acceptance fully.
        if result.returncode:
            assert "pygobject" in result.stderr.lower()
            pytest.skip("full aarch64 resolution needs Linux-compatible pygobject build metadata")
        results[label] = out.read_text()
    assert "mujoco==" not in results["base"]
    assert "onnxruntime==1.30.0" in results["voice"]
