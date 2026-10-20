"""BOT-SELF-TEST-02: the thin client for the service's two selftest routes.

The running StackChan service exposes GET /selftest/checks and POST
/selftest/run on loopback only. This module turns their JSON into the core's
CheckResult values and back, and gives one plain sentence when the service
cannot be reached or answers with a plain error of its own. Only names,
statuses, one line of detail and a fix ever travel here: no audio, pictures
or transcript text.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from maipai_body.selftest.core import CheckResult, Status

_STATUSES: dict[str, Status] = {status.value: status for status in Status}


class SelfTestUnreachable(RuntimeError):
    """The robot service did not answer at its address."""


class SelfTestServerError(RuntimeError):
    """The service answered with a plain error sentence of its own, for
    example an unknown check name in --only."""


def unreachable_message(url: str) -> str:
    return (
        f"The robot service did not answer at {url}. Start the Bot, or pass --url with its address."
    )


def results_from_json(payload: Mapping) -> list[CheckResult]:
    """Turn the service's {"results": [...]} reply into CheckResult values.
    Missing detail, fix and seconds default to "", "" and 0.0. A missing
    "results" list, a row without a name, or a status that is not pass,
    fail or skip raises ValueError with a plain sentence."""
    rows = payload.get("results") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        raise ValueError("The reply is not a selftest result list.")
    results: list[CheckResult] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("A result row is not a JSON object.")
        name = row.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("A result row has no check name.")
        raw_status = row.get("status")
        status = _STATUSES.get(raw_status) if isinstance(raw_status, str) else None
        if status is None:
            raise ValueError(f"Unknown status {raw_status!r} for check {name}.")
        detail = row.get("detail", "")
        fix = row.get("fix", "")
        seconds = row.get("seconds", 0.0)
        if not isinstance(detail, str) or not isinstance(fix, str):
            raise ValueError(f"Check {name} has a detail or fix that is not text.")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError(f"Check {name} has a seconds value that is not a number.")
        results.append(
            CheckResult(name=name, status=status, detail=detail, fix=fix, seconds=float(seconds))
        )
    return results


def results_to_json(results: Sequence[CheckResult]) -> dict[str, Any]:
    """The shape the service's POST /selftest/run reply uses."""
    return {
        "results": [
            {
                "name": result.name,
                "status": result.status.value,
                "detail": result.detail,
                "fix": result.fix,
                "seconds": result.seconds,
            }
            for result in results
        ]
    }


def _open(
    opener: Callable,
    url: str,
    *,
    data: bytes | None,
    headers: dict[str, str],
    timeout: float,
) -> Any:
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        return opener(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise SelfTestUnreachable(unreachable_message(url)) from exc


def _http_error(exc: urllib.error.HTTPError) -> RuntimeError:
    try:
        payload = json.loads(exc.read())
    except (ValueError, UnicodeDecodeError):
        payload = None
    if isinstance(payload, Mapping) and isinstance(payload.get("error"), str):
        return SelfTestServerError(payload["error"])
    return SelfTestUnreachable(unreachable_message(exc.url))


def fetch_checks(
    base_url: str,
    *,
    opener: Callable = urllib.request.urlopen,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """GET /selftest/checks: the name and title of every check the robot has."""
    url = base_url.rstrip("/") + "/selftest/checks"
    with _open(opener, url, data=None, headers={"Origin": base_url}, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("checks"), list):
        raise ValueError("The reply is not a selftest check list.")
    return list(payload["checks"])


def run_remote(
    base_url: str,
    only: Sequence[str] | None = None,
    *,
    opener: Callable = urllib.request.urlopen,
    timeout: float = 120.0,
) -> list[CheckResult]:
    """POST /selftest/run: run the robot's checks (or just the named ones)
    and come back with the per-part results. The Origin header equals
    base_url so the service's same-origin check passes."""
    url = base_url.rstrip("/") + "/selftest/run"
    body: dict[str, Any] = {}
    if only is not None:
        body["only"] = list(only)
    headers = {"Content-Type": "application/json", "Origin": base_url}
    with _open(
        opener, url, data=json.dumps(body).encode(), headers=headers, timeout=timeout
    ) as response:
        payload = json.load(response)
    return results_from_json(payload)
