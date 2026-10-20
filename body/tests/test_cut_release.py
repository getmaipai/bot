import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "cut-release.sh"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "PATH": os.environ.get("PATH", "")},
        check=False,
    )


def test_refuses_bad_tag() -> None:
    result = run("not-a-tag", "--signing-key", "/tmp/key.pem")
    assert result.returncode != 0
    assert "Invalid release tag" in result.stderr


def test_refuses_tag_that_does_not_match_package_version() -> None:
    result = run("v9.9.9", "--signing-key", "/tmp/key.pem")
    assert result.returncode != 0
    assert "does not match body version" in result.stderr


def test_requires_signing_key() -> None:
    result = run("v0.2.0")
    assert result.returncode != 0
    assert "Missing required --signing-key" in result.stderr
