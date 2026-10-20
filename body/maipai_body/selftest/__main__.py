"""BOT-SELF-TEST-02: run the robot's checks from a terminal.

Talks to the running service on loopback (GET /selftest/checks, POST
/selftest/run), prints one line per part plus a summary, and leaves the
shell's exit code as the verdict: 0 when no check failed, 1 when one did,
2 when the service did not answer or the server rejected the check names.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from io import TextIOBase

from maipai_body.selftest.client import (
    SelfTestServerError,
    SelfTestUnreachable,
    fetch_checks,
    run_remote,
)
from maipai_body.selftest.core import CheckResult, format_report, overall_ok

DEFAULT_URL = "http://127.0.0.1:8767"


def _parse_only(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    names = [name.strip() for name in raw.split(",")]
    return [name for name in names if name] or None


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIOBase = sys.stdout,
    runner: Callable[..., list[CheckResult]] = run_remote,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m maipai_body.selftest",
        description="Run the robot's selftest checks from a terminal.",
    )
    parser.add_argument(
        "--url", default=DEFAULT_URL, help="the service address (default %(default)s)"
    )
    parser.add_argument("--only", default=None, help="comma-separated check names to run")
    parser.add_argument(
        "--list", action="store_true", help="print the check names and titles, then stop"
    )
    args = parser.parse_args(argv)
    try:
        if args.list:
            for check in fetch_checks(args.url):
                print(f"{check['name']}  {check['title']}", file=stdout)
            return 0
        results = runner(args.url, _parse_only(args.only))
    except SelfTestUnreachable as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except SelfTestServerError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(format_report(results), file=stdout)
    return 0 if overall_ok(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
