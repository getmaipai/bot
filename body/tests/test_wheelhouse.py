"""The Bot release stages a complete, verified aarch64 wheelhouse."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPTS = ROOT / "scripts"


def test_builder_compiles_and_downloads_only_aarch64_cp312_binary_wheels():
    builder = (SCRIPTS / "build-wheelhouse.sh").read_text()
    for marker in (
        "manylinux2014_aarch64",
        "--python-version 3.12",
        "--implementation cp",
        "--abi cp312",
        "--only-binary=:all:",
        "--no-deps",
        "uv pip compile",
        "--extra voice",
        "--extra kws",
        "onnxruntime==1.30.0",
        "sherpa_onnx",
        ".sha256",
        "shasum",
    ):
        assert marker in builder


def test_install_dry_run_is_offline_and_installs_only_from_staged_wheelhouse(tmp_path):
    env, sync_calls = _install_env(tmp_path)
    wheel = tmp_path / "maipai_bot-0.1.0-py3-none-any.whl"
    wheel.touch()
    result = subprocess.run(
        [str(SCRIPTS / "install-reachy.sh"), "--dry-run", "example-host", str(wheel)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert not sync_calls.exists()
    plan = result.stdout.lower()
    assert "--no-index --find-links" in plan
    assert "wheelhouse-aarch64-cp312.tar" in plan
    assert "sha256sum" in plan
    assert "onnxruntime-1.30.0" in plan
    assert "sherpa_onnx" in plan
    assert "pypi" not in plan
    assert "--index-url" not in plan
    assert not re.search(r"pip install\s+[a-z][a-z0-9_-]+(?:$|\s)", plan)
    install_lines = [line for line in plan.splitlines() if "pip\\ install" in line]
    assert len(install_lines) == 2
    assert all("--no-index" in line and "--find-links" in line for line in install_lines)


def test_release_preparer_invokes_wheelhouse_builder_by_default():
    preparer = (SCRIPTS / "prepare-bot-release.sh").read_text()
    assert "build-wheelhouse.sh" in preparer
    assert "wheelhouse-aarch64-cp312.tar" in preparer
    assert "MAIPAI_SKIP_WHEELHOUSE" in preparer


def test_builder_refuses_to_create_a_partial_archive(tmp_path):
    result = subprocess.run(
        [str(SCRIPTS / "build-wheelhouse.sh"), "0.1.0", str(tmp_path)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    assert "release wheel" in result.stderr.lower()


def test_builder_requires_onxxruntime_sherpa_and_reachy_wheels_for_target():
    builder = (SCRIPTS / "build-wheelhouse.sh").read_text()
    assert 'ONNX=("$WHEELS"/onnxruntime-1.30.0-*aarch64*.whl)' in builder
    assert (
        'SHERPA=("$WHEELS"/sherpa_onnx-*aarch64*.whl "$WHEELS"/sherpa-onnx-*aarch64*.whl)'
    ) in builder
    assert 'REACHY=("$WHEELS"/reachy_mini-1.11.0-*.whl)' in builder
    assert '"${#ONNX[@]}" -ne 1' in builder
    assert '"${#SHERPA[@]}" -lt 1' in builder
    assert '"${#REACHY[@]}" -ne 1' in builder


def _install_env(tmp_path: Path):
    bin_dir = tmp_path / "uv-stub"
    bin_dir.mkdir(parents=True)
    calls = tmp_path / "uv-calls.log"
    stub = bin_dir / "uv"
    stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{calls}"\nexit 99\n')
    stub.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "MAIPAI_REACHY_HUB_ADDRESS": "192.168.1.10",
        "MAIPAI_REACHY_ROUTER_ADDRESS": "192.168.1.1",
        "MAIPAI_REACHY_SUBNET": "192.168.1.0/24",
    }
    return env, calls
