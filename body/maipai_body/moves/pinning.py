"""Pure helpers behind ``scripts/pin_moves_library.py`` (no network here).

Builds a library pin from already-downloaded move bytes: each clip's
sha256, the clip index from the dataset's ``metadata.jsonl``, and the
envelope report. A clip whose excursion leaves the profile's envelope is
listed as excluded with the axis that failed, never clipped.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from maipai_body.bodies.reachy_mini.envelope import clamp_target
from maipai_body.hal.errors import OutOfEnvelope
from maipai_body.hal.seam import BodyProfile

from .recorded_move import InvalidMove, RecordedMove


def parse_clip_index(metadata_jsonl: str) -> dict[str, str]:
    """Clip name to its description, from the dataset's ``metadata.jsonl``."""
    index: dict[str, str] = {}
    for line in metadata_jsonl.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        motion = str(row.get("motion_file", ""))
        if motion.endswith(".json"):
            index[motion.removesuffix(".json")] = str(row.get("description", ""))
    return index


def excursion_problem(name: str, raw: bytes, profile: BodyProfile) -> str | None:
    """Why this clip cannot play inside the envelope, or ``None`` when it can."""
    try:
        move = RecordedMove.from_json(name, json.loads(raw))
    except (InvalidMove, ValueError) as exc:
        return f"not a well-formed move: {exc}"
    for frame in move.frames:
        try:
            clamp_target(profile, frame.pose, frame.antennas, frame.body_yaw)
        except OutOfEnvelope as exc:
            return str(exc)
    return None


def build_pin(
    library: str,
    repo: str,
    revision: str,
    license_id: str,
    blobs: dict[str, bytes],
    metadata_jsonl: str,
    profile: BodyProfile,
) -> dict[str, Any]:
    files: dict[str, str] = {}
    excluded: dict[str, str] = {}
    descriptions = parse_clip_index(metadata_jsonl)
    clips: dict[str, str] = {}
    for name in sorted(blobs):
        problem = excursion_problem(name, blobs[name], profile)
        if problem is None:
            files[name] = hashlib.sha256(blobs[name]).hexdigest()
        else:
            excluded[name] = problem
        description = descriptions.get(name)
        if description is None:
            try:
                description = str(json.loads(blobs[name]).get("description", ""))
            except (ValueError, AttributeError):
                description = ""
        clips[name] = description
    return {
        "library": library,
        "repo": repo,
        "revision": revision,
        "license": license_id,
        "files": files,
        "excluded": excluded,
        "clips": clips,
    }
