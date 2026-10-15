"""Collect a structured StackChan unit-arrival measurement record."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


class MeasurementClient(Protocol):
    def measure_unit(self) -> dict[str, Any]: ...


def collect_results(client: MeasurementClient, *, source: str = "paired-unit") -> dict[str, Any]:
    """Collect measurements from a paired unit or a labeled simulator fixture."""
    data = client.measure_unit()
    required = {"servo_limits_deg", "camera", "aec", "battery", "base_mcp_tools"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"measurement source omitted fields: {', '.join(sorted(missing))}")
    limits = data["servo_limits_deg"]
    if limits.get("pitch") != [5, 85]:
        data["servo_limits_recommendation"] = "pitch 5..85 degrees"
    return {
        "schema_version": 1,
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "source": source,
        "unit_verified": source == "paired-unit",
        "measurements": data,
    }


def write_results(client: MeasurementClient, output: Path, *, source: str) -> dict[str, Any]:
    results = collect_results(client, source=source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("stackchan-measurements.json"))
    parser.add_argument("--sim", action="store_true", help="use offline simulator fixture data")
    args = parser.parse_args()
    if not args.sim:
        parser.error(
            "live paired-unit transport is not wired yet; use --sim for a schema rehearsal"
        )
    from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient

    results = write_results(FakeStackChanDeviceClient(), args.output, source="simulator")
    print(f"Wrote {args.output} (unit_verified={results['unit_verified']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
