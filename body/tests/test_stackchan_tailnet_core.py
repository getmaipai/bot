"""The robot's own tailnet client: its pure choices (firmware patch 147), plain C, run on the host, and the recipe wiring."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FW = HERE.parent / "maipai_body/bodies/stackchan/firmware"
PATCH = FW / "patches/147-tailnet-client.patch"
C_TEST = HERE / "firmware" / "tailnet_core_test.c"


def core_header(tmp_path: Path) -> Path:
    """The core header exactly as patch 147 adds it (every added line of that new file)."""
    text = PATCH.read_text()
    block = text.split("+++ b/firmware/main/hal/maipai_tailnet_core.h\n", 1)[1]
    body = block.split("\n", 1)[1]  # drop the @@ line
    lines = []
    for line in body.splitlines():
        if line.startswith("diff --git"):
            break
        if line.startswith("+"):
            lines.append(line[1:])
    header = tmp_path / "maipai_tailnet_core.h"
    header.write_text("\n".join(lines) + "\n")
    return header


def test_the_tailnet_core_passes_its_c_test(tmp_path: Path):
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler on this machine")
    core_header(tmp_path)
    binary = tmp_path / "tailnet_core_test"
    build = subprocess.run(
        [cc, "-std=c99", "-D_DEFAULT_SOURCE", "-Wall", "-Werror", f"-I{tmp_path}", str(C_TEST), "-o", str(binary)],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all checks passed" in run.stdout


def test_the_patches_are_listed_in_the_recipe_in_order():
    recipe = (FW / "recipe.sh").read_text()
    order = [
        recipe.index(f"apply_repo_patch {name}")
        for name in (
            "146-fallback-gateway-and-ssid-gate.patch",
            "147-tailnet-client.patch",
            "148-tailnet-endpoint.patch",
        )
    ]
    assert order == sorted(order)
    assert "149-microlink-psram-stacks.patch" in recipe


def test_microlink_is_pinned_by_commit_and_never_vendored():
    pins = (FW / "pins.toml").read_text()
    assert "[tailnet]" in pins
    assert 'repository = "https://github.com/Csontikka/microlink.git"' in pins
    assert 'commit = "a85e8c42ee2ed3223f8c3bd3766fc37af1985384"' in pins
    recipe = (FW / "recipe.sh").read_text()
    assert "--tailnet-authkey-file" in recipe
    assert 'ML_DIR="$BUILD_ROOT/deps/microlink"' in recipe  # outside the StackChan source tree


def test_no_auth_key_is_ever_in_the_repo():
    for path in (FW / "patches").glob("14[7-9]-*.patch"):
        text = path.read_text()
        assert "tskey-" not in text
    assert 'default ""' in PATCH.read_text().split("STACKCHAN_TAILNET_AUTHKEY", 1)[1][:400]
