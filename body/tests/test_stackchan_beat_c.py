"""Compile and run the standalone C beat phase helper."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
HEADER = HERE.parent / "maipai_body/bodies/stackchan/firmware/assets/maipai_beat.h"
C_TEST = HERE / "firmware/beat_test.c"


@pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler on this machine")
def test_c_beat_phase(tmp_path: Path) -> None:
    binary = tmp_path / "beat_test"
    build = subprocess.run(
        [
            "cc",
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{HEADER.parent}",
            str(C_TEST),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all passed" in result.stdout
