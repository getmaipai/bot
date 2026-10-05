"""The header every recorded run carries, and where a run is written.

``docs/dev/measurements.md``'s rule: mode, daemon version, profile id and
date on every run; never a hostname, never a household recording.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_MODES = ("sim", "unit")
_FORBIDDEN_KEYS = {"host", "hostname", "node", "fqdn"}


def new_run_header(
    *,
    row: str,
    mode: str,
    profile_id: str,
    daemon_version: str,
    image_release: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}, not {mode!r}")
    return {
        "row": row,
        "mode": mode,
        "profile": profile_id,
        "daemon_version": daemon_version,
        "image_release": image_release,
        "date": date or time.strftime("%Y-%m-%d", time.gmtime()),
    }


def _reject_hostnames(value: Any) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"a recorded run never carries a {key!r} field")
            _reject_hostnames(inner)
    elif isinstance(value, list):
        for inner in value:
            _reject_hostnames(inner)


def write_run(
    out_dir: Path, header: dict[str, Any], rows: list[dict[str, Any]], *, tag: str | None = None
) -> Path:
    """Write one run as ``<row>-<mode>[-<tag>]-<date>.json`` under ``out_dir``."""
    _reject_hostnames(header)
    _reject_hostnames(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = "-".join(part for part in (header["row"], header["mode"], tag, header["date"]) if part)
    path = out_dir / f"{stem}.json"
    path.write_text(json.dumps({"header": header, "rows": rows}, indent=2) + "\n")
    return path


def upsert_markdown_section(path: Path, heading_prefix: str, section: str) -> None:
    """Replace the section whose heading starts with ``heading_prefix``, or append it.

    A section runs to the next ``## `` heading. Other rows' sections are
    never touched, so recording one measurement cannot erase another.
    """
    text = path.read_text() if path.exists() else ""
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.startswith(heading_prefix)), None)
    if start is None:
        if text and not text.endswith("\n"):
            text += "\n"
        if text and not text.endswith("\n\n"):
            text += "\n"
        path.write_text(text + section)
        return
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    path.write_text("".join(lines[:start]) + section + "\n" + "".join(lines[end:]))
