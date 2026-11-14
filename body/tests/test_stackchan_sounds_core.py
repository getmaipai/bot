"""The unit's sound logic (firmware patch 115) is plain C: compile and run its test on the host."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent / "maipai_body/bodies/stackchan/firmware"
PATCHES = FIRMWARE / "patches"
PATCH = PATCHES / "115-sounds-core.patch"
C_TEST = HERE / "firmware" / "sounds_core_test.c"


POWER_PATCH = PATCHES / "141-power-reading-and-sound-gate.patch"


def header_from_patch(tmp_path: Path) -> str:
    """The core header as patch 115 adds it, then patch 141's hunks for that file applied on top."""
    text = PATCH.read_text()
    block = text.split("+++ b/firmware/main/hal/maipai_sounds_core.h\n", 1)[1]
    body = block.split("\n", 1)[1]  # drop the @@ line
    header = "\n".join(line[1:] for line in body.splitlines() if line.startswith("+")) + "\n"
    target = tmp_path / "firmware/main/hal"
    target.mkdir(parents=True)
    (target / "maipai_sounds_core.h").write_text(header)
    diff = POWER_PATCH.read_text()
    start = diff.index("diff --git")
    only = re.split(r"(?m)^(?=diff --git )", diff[start:])
    core = [
        part
        for part in only
        if part.strip() and "a/firmware/main/hal/maipai_sounds_core.h" in part.splitlines()[0]
    ]
    assert core, "patch 141 must change the core header"
    (tmp_path / "core.diff").write_text(core[0])
    applied = subprocess.run(
        ["git", "apply", "--unidiff-zero", "--whitespace=nowarn", "core.diff"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert applied.returncode == 0, applied.stderr
    return (target / "maipai_sounds_core.h").read_text()


@pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler on this machine")
def test_sound_core_c_tests_pass(tmp_path):
    (tmp_path / "maipai_sounds_core.h").write_text(header_from_patch(tmp_path))
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
            binary,
        ],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all passed" in run.stdout


def test_the_patch_series_is_wired_into_the_recipe_in_order():
    recipe = (FIRMWARE / "recipe.sh").read_text()
    order = [
        m.group(1)
        for m in re.finditer(r"^apply_repo_patch (11[5-8]-[\w-]+\.patch) ", recipe, re.MULTILINE)
    ]
    assert order == [
        "115-sounds-core.patch",
        "116-sounds-device.patch",
        "117-sound-events.patch",
        "118-offline-phrases.patch",
    ]
    for name in order:
        assert (PATCHES / name).is_file()
        assert "—" not in (PATCHES / name).read_text()  # no em dashes


def test_the_recipe_embeds_the_earcons_and_packs_the_phrases_and_cleans_up():
    recipe = (FIRMWARE / "recipe.sh").read_text()
    assert "assets/sounds/snd_$earcon.ogg" in recipe  # copied into main/assets/sfx (embedded)
    assert "assets/phrases/ph_*.ogg" in recipe  # copied into assets_bin (the assets image)
    assert (
        "snd_*.ogg" in recipe
        and "ph_*.ogg"
        in recipe.split("cleanup_firmware_tree()")[1].split("trap cleanup_firmware_tree")[0]
    )
    cmake = (PATCHES / "116-sounds-device.patch").read_text()
    assert "needs_you plug_in charged unplug offline goodbye shutter" in cmake
