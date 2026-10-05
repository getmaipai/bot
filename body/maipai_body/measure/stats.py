"""Percentiles for measurement rows."""

from __future__ import annotations

import math
from collections.abc import Sequence


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile: always one of the observed values.

    Interpolating would report a p95 nobody ever saw; with the small
    sample counts a bench run produces, the observed value is the
    honest one.
    """
    if not values:
        raise ValueError("percentile of no values")
    if not 0 <= q <= 100:
        raise ValueError(f"quantile {q} is outside 0 to 100")
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize(values: Sequence[float]) -> dict[str, float | int | None]:
    """Count, p50, p95, min and max; no numbers (never zeros) for no samples."""
    if not values:
        return {"n": 0, "p50": None, "p95": None, "min": None, "max": None}
    return {
        "n": len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "min": min(values),
        "max": max(values),
    }
