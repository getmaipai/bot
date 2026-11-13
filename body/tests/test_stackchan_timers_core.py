"""The on-unit timer logic (firmware patch 090) is plain C: compile and run its test on the host."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PATCH = HERE.parent / "maipai_body/bodies/stackchan/firmware/patches/090-timers-core.patch"
C_TEST = HERE / "firmware" / "timers_core_test.c"


def _header_from_patch() -> str:
    text = PATCH.read_text()
    block = text.split("+++ b/firmware/main/hal/maipai_timers_core.h\n", 1)[1]
    body = block.split("\n", 1)[1]  # drop the @@ line
    return "\n".join(line[1:] for line in body.splitlines() if line.startswith("+")) + "\n"


@pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler on this machine")
def test_timer_core_c_tests_pass(tmp_path):
    (tmp_path / "maipai_timers_core.h").write_text(_header_from_patch())
    binary = tmp_path / "core_test"
    build = subprocess.run(
        [
            "cc",
            "-std=c99",
            "-Wall",
            "-Wextra",
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
    assert "all passed" in run.stdout


def test_the_patch_series_is_wired_into_the_recipe_in_order():
    recipe = (PATCH.parent.parent / "recipe.sh").read_text()
    order = [
        m.group(1)
        for m in re.finditer(r"^apply_repo_patch (09[0-4]-[\w-]+\.patch) ", recipe, re.MULTILINE)
    ]
    assert order == [
        "090-timers-core.patch",
        "091-timers-device.patch",
        "092-timer-tools.patch",
        "093-timer-touch-stop.patch",
        "094-timer-stop-word.patch",
    ]
    for name in order:
        assert (PATCH.parent / name).is_file()
