"""The away-from-home fallback choices (firmware patch 146): plain C, run on the host."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PATCH = (
    HERE.parent
    / "maipai_body/bodies/stackchan/firmware/patches/146-fallback-gateway-and-ssid-gate.patch"
)
C_TEST = HERE / "firmware" / "fallback_core_test.c"


def core_header(tmp_path: Path) -> Path:
    """The core header exactly as patch 146 adds it (every added line of that new file)."""
    text = PATCH.read_text()
    block = text.split("+++ b/firmware/main/hal/maipai_fallback_core.h\n", 1)[1]
    body = block.split("\n", 1)[1]  # drop the @@ line
    lines = []
    for line in body.splitlines():
        if line.startswith("diff --git"):
            break
        if line.startswith("+"):
            lines.append(line[1:])
    header = tmp_path / "maipai_fallback_core.h"
    header.write_text("\n".join(lines) + "\n")
    return header


def test_the_fallback_core_passes_its_c_test(tmp_path: Path):
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler on this machine")
    core_header(tmp_path)
    binary = tmp_path / "fallback_core_test"
    build = subprocess.run(
        [
            cc,
            "-std=c99",
            "-D_DEFAULT_SOURCE",
            "-Wall",
            "-Werror",
            f"-I{tmp_path}",
            str(C_TEST),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all checks passed" in run.stdout


def test_the_patch_is_listed_in_the_recipe_after_144_and_145():
    recipe = (PATCH.parent.parent / "recipe.sh").read_text()
    order = [
        recipe.index(f"apply_repo_patch {name}")
        for name in (
            "144-fallback-hub-endpoint.patch",
            "145-app-version-from-release.patch",
            "146-fallback-gateway-and-ssid-gate.patch",
        )
    ]
    assert order == sorted(order)
