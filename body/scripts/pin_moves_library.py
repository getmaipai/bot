"""Pin Pollen's emotions and dances libraries: write ``moves/pins.json`` from the live datasets.

Usage (from ``body/``, on the dev Mac, needs network to huggingface.co)::

    uv run python scripts/pin_moves_library.py

Resolves each dataset's current commit, downloads every ``*.json`` move
and ``metadata.jsonl`` at that exact revision, and records the revision,
the licence the dataset card states, each playable file's sha256, the
clip index and the clips excluded for leaving the Reachy Mini envelope
(reported, never clipped). Refuses a library whose card states no
Apache-2.0 licence. Only motion JSON is read (no Opus sidecars, no code
repository). The pins go into the optional moves package's manifest in
the catalog; review the diff before committing. Nothing downloaded is
kept: only names, checksums and descriptions are written.
"""

from __future__ import annotations

import json
import sys

import requests

from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.moves.library import PINS_PATH
from maipai_body.moves.pinning import build_pin

LIBRARIES = {
    "emotions": "pollen-robotics/reachy-mini-emotions-library",
    "dances": "pollen-robotics/reachy-mini-dances-library",
}
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
    base = f"https://huggingface.co/datasets/{repo}/resolve/{revision}"
    blobs: dict[str, bytes] = {}
    metadata = ""
    for sibling in body["siblings"]:
        name = sibling["rfilename"]
        if name == "metadata.jsonl":
            raw = requests.get(f"{base}/{name}", timeout=60)
            raw.raise_for_status()
            metadata = raw.text
        elif name.endswith(".json") and "/" not in name:
            raw = requests.get(f"{base}/{name}", timeout=60)
            raw.raise_for_status()
            blobs[name.removesuffix(".json")] = raw.content
    return build_pin(library, repo, revision, "Apache-2.0", blobs, metadata, REACHY_MINI_PROFILE)


def main() -> None:
    pins = [pin_library(library, repo) for library, repo in LIBRARIES.items()]
    PINS_PATH.write_text(json.dumps({"pins": pins}, indent=2) + "\n")
    for pin in pins:
        print(
            f"{pin['library']}: pinned {len(pin['files'])} moves, excluded {len(pin['excluded'])}"
        )
        for name, reason in pin["excluded"].items():
            print(f"  excluded {name}: {reason}")


if __name__ == "__main__":
    main()
