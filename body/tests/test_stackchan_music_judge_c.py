"""The plain C music judge equals the production Python judge on fixtures and a seeded sweep."""

from __future__ import annotations

import random
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from test_stackchan_music_dance import MUSIC, NO_BEAT, NOISE, SPEECH, TALK_PAUSES

from maipai_body.bodies.stackchan.music_dance import SENSITIVITIES, MusicFeat, judge

HERE = Path(__file__).resolve().parent
HEADER = HERE.parent / "maipai_body/bodies/stackchan/firmware/assets/maipai_music_judge.h"
C_TEST = HERE / "firmware/music_judge_test.c"


def _vectors() -> list[MusicFeat]:
    wandering = replace(MUSIC, tc=15, fl=90, bpm=187, mo=20, ps=5)
    fixtures = [MUSIC, SPEECH, TALK_PAUSES, NOISE, NO_BEAT, wandering]
    rng = random.Random(20261113)
    vectors = fixtures[:]
    for _ in range(320):
        vectors.append(
            MusicFeat(
                lv=rng.randint(0, 3500),
                b=(0, 0, 0, 0),
                bpm=rng.randint(0, 240),
                tc=rng.randint(0, 100),
                fl=rng.randint(0, 110),
                zc=0,
                zs=0,
                mo=rng.randint(0, 100),
                ps=rng.randint(0, 100),
                muted=bool(rng.getrandbits(1)),
            )
        )
    return vectors


@pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler on this machine")
def test_c_judge_matches_python(tmp_path: Path) -> None:
    rows = []
    for feat in _vectors():
        for sensitivity in SENSITIVITIES:
            for relaxed in (False, True):
                verdict = judge(feat, sensitivity, relaxed=relaxed)
                rows.append(
                    f"{feat.lv} {feat.bpm} {feat.tc} {feat.fl} {feat.mo} {feat.ps} "
                    f"{int(feat.muted)} {list(SENSITIVITIES).index(sensitivity)} "
                    f"{int(relaxed)} {int(verdict.music)} {verdict.why}\n"
                )
    data = tmp_path / "vectors.txt"
    data.write_text("".join(rows))
    binary = tmp_path / "music_judge_test"
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
    result = subprocess.run([str(binary), str(data)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all passed" in result.stdout
    assert len(rows) >= 300
