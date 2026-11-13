"""The on-unit music features (firmware patch 100) are plain C: compile the header from the patch,
run its test on synthesized signals, then ask the shipped host decision layer (music_dance.judge)
about each signal's numbers. A beat track must read as music; a steady tone, white noise, noise
amplitude-modulated at 4 Hz, a syllable pattern and a quiet room must not."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from maipai_body.bodies.stackchan.music_dance import MusicFeat, judge

HERE = Path(__file__).resolve().parent
PATCH_DIR = HERE.parent / "maipai_body/bodies/stackchan/firmware/patches"
PATCH = PATCH_DIR / "100-music-features.patch"
C_TEST = HERE / "firmware" / "music_core_test.c"
HEADER = "maipai_music_core.h"

pytestmark = pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler on this machine")


def _header_from_patch() -> str:
    text = PATCH.read_text()
    block = text.split(f"+++ b/firmware/main/hal/{HEADER}\n", 1)[1]
    body = block.split("\n", 1)[1]  # drop the @@ line
    lines = []
    for line in body.splitlines():
        if line.startswith("diff --git"):
            break
        if line.startswith("+"):
            lines.append(line[1:])
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def c_output(tmp_path_factory) -> str:
    tmp = tmp_path_factory.mktemp("music_core")
    (tmp / HEADER).write_text(_header_from_patch())
    binary = tmp / "core_test"
    build = subprocess.run(
        [
            "cc",
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{tmp}",
            str(C_TEST),
            "-o",
            str(binary),
            "-lm",
        ],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    return run.stdout


def _features(output: str) -> dict[str, MusicFeat]:
    found = {}
    for line in output.splitlines():
        if not line.startswith("FEAT "):
            continue
        name = line.split()[1]
        values = dict(part.split("=", 1) for part in line.split()[2:])
        b = [int(x) for x in values["b"].split(",")]
        found[name] = MusicFeat(
            lv=int(values["lv"]),
            b=(b[0], b[1], b[2], b[3]),
            bpm=int(values["bpm"]),
            tc=int(values["tc"]),
            fl=int(values["fl"]),
            zc=int(values["zc"]),
            zs=int(values["zs"]),
            mo=int(values["mo"]),
            ps=int(values["ps"]),
            on=int(values["on"]),
        )
    return found


def test_the_c_checks_pass(c_output):
    assert "all passed" in c_output


def test_the_header_also_compiles_as_cpp(tmp_path):
    """The firmware includes it from C++ (hal_music.cpp)."""
    if shutil.which("c++") is None:
        pytest.skip("no C++ compiler")
    (tmp_path / HEADER).write_text(_header_from_patch())
    unit = tmp_path / "u.cpp"
    unit.write_text(
        f'#include "{HEADER}"\nint main() {{ mm_an_t* a = nullptr; (void)a; return 0; }}\n'
    )
    result = subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{tmp_path}",
            "-fsyntax-only",
            str(unit),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", ["click120", "click90", "click150", "music120", "music100"])
@pytest.mark.parametrize("sensitivity", ["low", "medium", "high"])
def test_beat_tracks_read_as_music(c_output, name, sensitivity):
    feat = _features(c_output)[name]
    verdict = judge(feat, sensitivity)
    assert verdict.music, f"{name} at {sensitivity}: {verdict.why} ({feat})"


@pytest.mark.parametrize("name", ["sine", "white", "am4noise", "syllables", "quiet"])
@pytest.mark.parametrize("sensitivity", ["low", "medium", "high"])
def test_tone_noise_speech_like_and_quiet_do_not(c_output, name, sensitivity):
    feat = _features(c_output)[name]
    verdict = judge(feat, sensitivity)
    assert not verdict.music, f"{name} at {sensitivity} read as music ({feat})"


def test_the_tempo_is_found_within_two_beats_a_minute(c_output):
    found = _features(c_output)
    for name, bpm in (("click120", 120), ("click90", 90), ("click150", 150), ("music100", 100)):
        assert abs(found[name].bpm - bpm) <= 2, name


def test_the_patch_series_is_wired_into_the_recipe_in_order():
    recipe = (PATCH_DIR.parent / "recipe.sh").read_text()
    order = [
        m.group(1)
        for m in re.finditer(r"^apply_repo_patch (10[01]-[\w-]+\.patch) ", recipe, re.MULTILINE)
    ]
    assert order == ["100-music-features.patch", "101-music-tap.patch"]
    for name in order:
        assert (PATCH_DIR / name).is_file()
    assert 'apply_repo_patch 100-music-features.patch "$SRC"' in recipe
    assert 'apply_repo_patch 101-music-tap.patch "$FW/xiaozhi-esp32"' in recipe


def test_the_event_carries_only_numbers_and_stays_small():
    """The privacy line: the firmware's event is a handful of integers, never audio."""
    source = "\n".join(line[1:] for line in PATCH.read_text().splitlines() if line.startswith("+"))
    string = r'"(?:[^"\\]|\\.)*"'
    fmt = re.search(rf"snprintf\(extra, sizeof\(extra\),\s*((?:{string}\s*)+),", source)
    assert fmt, "the music_feat event format was not found"
    text = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', fmt.group(1))).replace('\\"', '"')
    assert text.count("%d") == 13
    assert "%s" not in text and "%f" not in text
    # worst case: the level at five digits (int16 range), every other field at three; buffer 128
    worst = re.sub(r"%d", "123", text).replace('"lv":123', '"lv":12345')
    assert len(worst) < 128
