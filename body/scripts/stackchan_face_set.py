#!/usr/bin/env python3
"""Extract face names from a local M5 StackChan avatar source checkout."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

DEFAULT_OUTPUT = (
    Path(__file__).parents[1] / "maipai_body" / "bodies" / "stackchan" / "face_set.json"
)


def _source_commit(source: Path, requested: str | None) -> str:
    if requested:
        return requested
    try:
        return subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("source checkout is not a git repository; pass --commit") from exc


def extract_faces(source: Path) -> tuple[str, list[str]]:
    candidates = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in {".cpp", ".cc", ".c", ".h", ".hpp"}
    )
    patterns = (
        re.compile(r"enum\s+(?:class\s+)?\w*(?:Expression|Emotion)\w*\s*\{([^}]+)\}", re.S),
        re.compile(
            r"(?:expression|emotion)(?:Names|List|Values)\s*\[[^]]*\]\s*=\s*\{([^}]+)\}",
            re.I | re.S,
        ),
    )
    for path in candidates:
        text = path.read_text(errors="replace")
        values: set[str] = set()
        for pattern in patterns:
            for match in pattern.finditer(text):
                block = re.sub(r"//[^\n]*|/\*.*?\*/", "", match.group(1), flags=re.S)
                for item in re.findall(r'"([a-z][a-z0-9_-]*)"|\b([A-Z][a-z0-9_-]*)\b', block):
                    value = next((part for part in item if part), "")
                    if value:
                        values.add(value.lower())
        if values:
            return path.relative_to(source).as_posix(), sorted(values)
    raise ValueError("no avatar Expression/Emotion enum or name list found in source checkout")


def generate(source: Path, commit: str | None) -> bytes:
    relative_file, faces = extract_faces(source)
    data = {
        "source_file": relative_file,
        "upstream_commit": _source_commit(source, commit),
        "faces": faces,
    }
    return (json.dumps(data, indent=2) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="local checkout of m5stack/StackChan")
    parser.add_argument("--commit", help="source commit (defaults to the local checkout HEAD)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        payload = generate(args.source, args.commit)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    args.output.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
