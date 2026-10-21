"""Firmware patches 046 and later carry context lines, so they land where they were written.

Patches 046 to 059 were first written as zero-context diffs. `git apply --unidiff-zero` places a
zero-context insertion by line number alone and cannot check it, and the recipe's tree differs from
the scratch tree they were written against by a few lines: patch 047 landed inside the wrong branch
of `HandleToggleChatEvent` in every build from 0.2.20 to 0.2.28 (a tap at rest started listening and
then aborted at once). Context lines make the apply check verify the location.
"""

from __future__ import annotations

import re
from pathlib import Path

PATCHES = Path(__file__).resolve().parents[1] / "maipai_body/bodies/stackchan/firmware/patches"
_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,\d+)? @@")


def _hunks_without_context(text: str) -> list[str]:
    bad: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = _HUNK.match(lines[i])
        if not match:
            i += 1
            continue
        start = i
        i += 1
        context = 0
        while i < len(lines) and not lines[i].startswith(("@@", "diff --git")):
            if lines[i].startswith(" "):
                context += 1
            i += 1
        if context == 0 and not lines[start].startswith("@@ -0,0 "):  # a new file has no context
            bad.append(lines[start])
    return bad


def test_patches_from_046_on_have_context_in_every_hunk():
    problems: dict[str, list[str]] = {}
    for patch in sorted(PATCHES.glob("[0-9][0-9][0-9]-*.patch")):
        if int(patch.name[:3]) < 46:
            continue
        bad = _hunks_without_context(patch.read_text())
        if bad:
            problems[patch.name] = bad[:3]
    assert not problems, f"zero-context hunks (regenerate with git diff -U3): {problems}"
