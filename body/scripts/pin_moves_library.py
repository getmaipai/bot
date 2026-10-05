"""Pin Pollen's emotions library: write ``moves/pins.json`` from the live dataset.

Usage (from ``body/``, needs network to huggingface.co)::

    uv run python scripts/pin_moves_library.py

Resolves the dataset's current commit, downloads every ``*.json`` move at
that exact revision, and records the revision, the licence the dataset
card states and each file's sha256 in ``maipai_body/moves/pins.json``.
Refuses to pin a library whose card states no Apache-2.0 licence, and
never touches the dances library (excluded until its licence is stated).
Review the diff of ``pins.json`` before committing it. Nothing downloaded
is kept: only names and checksums are written.
"""

from __future__ import annotations

import hashlib
import json
import sys

import requests

from maipai_body.moves.library import PINS_PATH

LIBRARIES = {"emotions": "pollen-robotics/reachy-mini-emotions-library"}
API = "https://huggingface.co/api/datasets"


def pin_library(library: str, repo: str) -> dict:
    info = requests.get(f"{API}/{repo}", timeout=30)
    info.raise_for_status()
    body = info.json()
    revision = body["sha"]
    license_id = next(
        (tag.split(":", 1)[1] for tag in body.get("tags", []) if tag.startswith("license:")), ""
    )
    if license_id.lower() != "apache-2.0":
        sys.exit(f"{repo}: card states licence {license_id!r}, not apache-2.0; not pinned")
    files: dict[str, str] = {}
    for sibling in body["siblings"]:
        name = sibling["rfilename"]
        if not name.endswith(".json") or "/" in name:
            continue
        raw = requests.get(
            f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{name}", timeout=60
        )
        raw.raise_for_status()
        files[name.removesuffix(".json")] = hashlib.sha256(raw.content).hexdigest()
    return {
        "library": library,
        "repo": repo,
        "revision": revision,
        "license": "Apache-2.0",
        "files": dict(sorted(files.items())),
    }


def main() -> None:
    pins = [pin_library(library, repo) for library, repo in LIBRARIES.items()]
    PINS_PATH.write_text(json.dumps({"pins": pins}, indent=2) + "\n")
    print(f"pinned {sum(len(p['files']) for p in pins)} moves in {PINS_PATH}")


if __name__ == "__main__":
    main()
