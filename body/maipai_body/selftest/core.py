"""BOT-SELF-TEST-01: the small check runner every per-part self-test shares.

One check is one part of one bot. A person (or Home) runs the list and gets
pass or fail per part, each with a plain "what to do" on failure. Nothing is
kept: the results carry only names, statuses, one line of detail and a fix,
never audio, pictures or transcript text.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum

FAILURE_FIX = "Retry; if it fails again, send this line to the person who set up the robot."


class Status(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    detail: str
    fix: str = ""
    seconds: float = 0.0


@dataclass(frozen=True)
class Check:
    """One part check. ``run`` returns ``(Status, detail, fix)`` or raises;
    ``None`` means the part is not present and the check is skipped.
    ``needs`` names the context capabilities the check requires."""

    name: str
    title: str
    needs: tuple[str, ...]
    run: Callable[[], tuple[Status, str, str]] | None


def run_selftest(
    checks: Sequence[Check],
    *,
    only: Collection[str] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> list[CheckResult]:
    """Run the checks in order. One failing check never stops the run: an
    exception in a check becomes a FAIL with the exception named in its
    detail and a plain fix, and the later checks still run."""
    names = [check.name for check in checks]
    selected = list(checks)
    if only is not None:
        unknown = [name for name in only if name not in names]
        if unknown:
            raise ValueError(
                "unknown check name(s): "
                + ", ".join(sorted(unknown))
                + "; valid names: "
                + ", ".join(names)
            )
        wanted = set(only)
        selected = [check for check in checks if check.name in wanted]
    results: list[CheckResult] = []
    for check in selected:
        start = clock()
        if check.run is None:
            results.append(CheckResult(name=check.name, status=Status.SKIP, detail=check.title))
            continue
        try:
            status, detail, fix = check.run()
        except Exception as exc:
            results.append(
                CheckResult(
                    name=check.name,
                    status=Status.FAIL,
                    detail=f"{type(exc).__name__}: {exc}",
                    fix=FAILURE_FIX,
                    seconds=clock() - start,
                )
            )
        else:
            results.append(
                CheckResult(
                    name=check.name, status=status, detail=detail, fix=fix, seconds=clock() - start
                )
            )
    return results


def format_report(results: Sequence[CheckResult]) -> str:
    """One line per check, an indented ``fix:`` line after any result that
    carries a fix, and a final summary line. No em dashes."""
    lines: list[str] = []
    for result in results:
        label = result.status.value.upper()
        lines.append(f"{label:<4}  {result.name:<10} {result.detail}")
        if result.fix:
            lines.append(f"    fix: {result.fix}")
    passed = sum(1 for result in results if result.status is Status.PASS)
    failed = sum(1 for result in results if result.status is Status.FAIL)
    skipped = sum(1 for result in results if result.status is Status.SKIP)
    lines.append(f"{passed} passed, {failed} failed, {skipped} skipped")
    return "\n".join(lines)


def overall_ok(results: Sequence[CheckResult]) -> bool:
    """True when no check failed; skips do not count against the run."""
    return all(result.status is not Status.FAIL for result in results)
