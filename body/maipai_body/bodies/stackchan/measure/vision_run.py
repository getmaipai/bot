"""Offline fixture scoring and unit-ready StackChan vision measurement plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

CONDITIONS = [(distance, light) for distance in (0.5, 1.0, 1.5) for light in ("room", "dim")]


def summarize(rows: list[dict[str, object]], fixture_dir: Path) -> dict[str, object]:
    frames = []
    for row in rows:
        frame_path = fixture_dir / str(row.get("frame", ""))
        if not frame_path.is_file():
            raise ValueError(f"fixture frame is missing: {frame_path}")
        frame = np.load(frame_path, allow_pickle=False)
        if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError(f"fixture frame must be a uint8 HxWx3 array: {frame_path}")
        frames.append({"frame": frame_path.name, "shape": list(frame.shape)})
        del frame
    report: dict[str, object] = {
        "hardware_verified": False,
        "conditions": [],
        "fixture_frames_loaded": len(frames),
        "fixture_frame_details": frames,
    }
    conditions = []
    for distance, light in CONDITIONS:
        group = [
            r
            for r in rows
            if not r.get("placeholder")
            and r.get("distance_m") == distance
            and r.get("light") == light
        ]
        positives = [r for r in group if r.get("expected_person")]
        negatives = [r for r in group if not r.get("expected_person")]
        matches = sum(r.get("predicted_person") == r.get("expected_person") for r in positives)
        false_accepts = sum(bool(r.get("predicted_person")) for r in negatives)
        conditions.append(
            {
                "distance_m": distance,
                "light": light,
                "match_rate": matches / len(positives) if positives else None,
                "false_accept_rate": false_accepts / len(negatives) if negatives else None,
                "positive_samples": len(positives),
                "negative_samples": len(negatives),
            }
        )
    report["conditions"] = conditions
    report["note"] = (
        "Fixture scores are offline software checks; "
        "populate with unit measurements before making range claims."
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "fixture", type=Path, help="JSON list of persona-free labeled fixture verdicts"
    )
    args = parser.parse_args()
    rows = json.loads(args.fixture.read_text())
    if not isinstance(rows, list):
        parser.error("fixture must contain a JSON list of labeled samples")
    print(json.dumps(summarize(rows, args.fixture.parent), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
