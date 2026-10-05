"""M-R4: battery. Runtime by the clock, and what the unit can say about its own charge.

Design record section 12: runtime idle, in conversation every two minutes,
and with tracking on, measured by the clock from full to the LED's red;
whether any readable fact (a voltage, a charger-present flag) exists on the
unit; whether it runs while charging. Until this row exists the card says
"battery level unknown".

The unit has no readout the design knows of, so two things are built to
find out: a probe over every place a fact could be (the kernel's power
supplies, the daemon's own status and routes), and a heartbeat log
that survives the power dying under it (each line flushed and fsynced), so
the last line's boot-clock time is the runtime. Nothing here assumes the
answer; an empty probe is a result.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

from maipai_body.measure.budget import decode_throttled, parse_throttled

POWER_SUPPLY_ROOT = Path("/sys/class/power_supply")
_SUPPLY_FILES = (
    "capacity",
    "voltage_now",
    "voltage_min_design",
    "current_now",
    "status",
    "online",
    "present",
    "charge_now",
    "energy_now",
    "health",
    "temp",
)
_FACT_KEY = re.compile(r"batt|volt|charg|soc|supply|power|current", re.IGNORECASE)
_FACT_PATH = re.compile(r"batt|volt|charg|supply|power", re.IGNORECASE)
_GAP_WARNING_INTERVALS = 3


def scan_power_supply(root: Path = POWER_SUPPLY_ROOT) -> list[dict[str, Any]]:
    """Every kernel power supply with the few values worth recording."""
    if not root.is_dir():
        return []
    found = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        values = {}
        for name in _SUPPLY_FILES:
            try:
                text = (entry / name).read_text().strip()
            except OSError:
                continue
            if text and len(text) <= 64 and "\n" not in text:
                values[name] = text
        try:
            kind = (entry / "type").read_text().strip()
        except OSError:
            kind = None
        found.append({"name": entry.name, "type": kind, "values": values})
    return found


def find_fact_keys(obj: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Every ``(dotted path, value)`` in nested JSON whose key looks like a power fact."""
    if not isinstance(obj, dict):
        return
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if _FACT_KEY.search(str(key)):
            yield path, value
        yield from find_fact_keys(value, path)


def daemon_getter(base_url: str) -> Callable[[str], Any]:
    import requests

    def get(path: str) -> Any:
        response = requests.get(f"{base_url}{path}", timeout=5)
        response.raise_for_status()
        return response.json()

    return get


def _run_command(command: Sequence[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, timeout=5, check=False).stdout


def probe_battery_facts(
    *,
    daemon_get: Callable[[str], Any],
    power_supply_root: Path = POWER_SUPPLY_ROOT,
    run_command: Callable[[Sequence[str]], str] = _run_command,
) -> dict[str, Any]:
    """Look everywhere a readable battery or charger fact could be, and report what is there."""
    supplies = scan_power_supply(power_supply_root)
    daemon_facts: list[dict[str, Any]] = []
    unreachable: list[str] = []
    for source in ("/api/daemon/status", "/api/state/full"):
        try:
            body = daemon_get(source)
        except Exception:
            unreachable.append(source)
            continue
        daemon_facts += [
            {"source": source, "path": path, "value": value} for path, value in find_fact_keys(body)
        ]
    try:
        openapi = daemon_get("/openapi.json")
        daemon_paths = sorted(p for p in openapi.get("paths", {}) if _FACT_PATH.search(p))
    except Exception:
        daemon_paths = []
        unreachable.append("/openapi.json")

    try:
        raw = parse_throttled(run_command(["vcgencmd", "get_throttled"]))
    except (OSError, subprocess.SubprocessError):
        raw = None
    flags = decode_throttled(raw) if raw is not None else None

    level = any(s["type"] == "Battery" for s in supplies) or any(
        re.search(r"batt|volt|soc", fact["path"], re.IGNORECASE) for fact in daemon_facts
    )
    charger = any(s["type"] in ("Mains", "USB") for s in supplies) or any(
        re.search(r"charg", fact["path"], re.IGNORECASE) for fact in daemon_facts
    )
    return {
        "readable": level or charger,
        "level_readable": level,
        "charger_readable": charger,
        "power_supply": supplies,
        "daemon_facts": daemon_facts,
        "daemon_paths": daemon_paths,
        "unreachable_sources": unreachable,
        # An input-rail sag flag is a hint a battery is running down, not a level.
        "indirect": {
            "under_voltage_flags": (
                None
                if flags is None
                else {k: flags[k] for k in ("under_voltage_now", "under_voltage_occurred")}
            )
        },
    }


def current_facts(
    supplies_root: Path = POWER_SUPPLY_ROOT,
) -> dict[str, str]:
    """The kernel power-supply values as ``{"<supply>.<file>": value}``, for the heartbeat."""
    return {
        f"{s['name']}.{key}": value
        for s in scan_power_supply(supplies_root)
        for key, value in s["values"].items()
    }


BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


def _boot_clock() -> float:
    """Seconds since boot. Linux (the unit's Compute Module) counts suspend too;
    elsewhere (a dev Mac rehearsing the tool) the nearest clock the OS has."""
    for name in ("CLOCK_BOOTTIME", "CLOCK_UPTIME_RAW"):
        clock_id = getattr(time, name, None)
        if clock_id is not None:
            return time.clock_gettime(clock_id)
    return time.monotonic()


def _read_boot_id(
    path: Path | None = None,
    boot_clock: Callable[[], float] = _boot_clock,
    wall_clock: Callable[[], float] = time.time,
) -> str:
    """The kernel's boot id, or where there is none a stand-in that still tells boots apart.

    ``path`` only exists on Linux. Without it the id is the boot's start
    time (wall clock minus time since boot) rounded to the minute, which is
    the same on every read within one boot and differs between boots; it
    is prefixed ``derived-`` so a log never passes it off as a kernel id.
    """
    try:
        return (path or BOOT_ID_PATH).read_text().strip()
    except OSError:
        return f"derived-{round((wall_clock() - boot_clock()) / 60) * 60}"


class HeartbeatLog:
    """An append-only JSONL log whose every line is on disk before the next is written."""

    def __init__(
        self,
        path: Path,
        *,
        boot_id: str | None = None,
        boot_clock: Callable[[], float] = _boot_clock,
    ) -> None:
        self._path = path
        self._boot_id = boot_id if boot_id is not None else _read_boot_id()
        self._boot_clock = boot_clock
        self._seq = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a", encoding="utf-8")  # noqa: SIM115 - held for the run

    def append(self, *, workload: str, extra: dict[str, Any]) -> None:
        record = {
            "seq": self._seq,
            "boot_id": self._boot_id,
            "t_boot_s": self._boot_clock(),
            "workload": workload,
            **extra,
        }
        self._file.write(json.dumps(record) + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())
        self._seq += 1

    def close(self) -> None:
        self._file.close()


def read_heartbeats(path: Path) -> list[dict[str, Any]]:
    """Every intact line; a final line cut short by the power going is dropped."""
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def analyze_runs(records: Sequence[dict[str, Any]], *, interval_s: float) -> list[dict[str, Any]]:
    """One run per boot: the span of its heartbeats, good to one interval."""
    by_boot: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_boot.setdefault(record["boot_id"], []).append(record)
    runs = []
    for boot_id, beats in by_boot.items():
        times = [b["t_boot_s"] for b in beats]
        gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
        max_gap = max(gaps, default=0.0)
        facts_seen: dict[str, dict[str, str]] = {}
        for beat in beats:
            for key, value in (beat.get("facts") or {}).items():
                facts_seen.setdefault(key, {"first": value, "last": value})["last"] = value
        runs.append(
            {
                "boot_id": boot_id,
                "workload": beats[0]["workload"],
                "charging": beats[-1].get("charging"),
                "heartbeats": len(beats),
                "runtime_s": times[-1] - times[0],
                "uncertainty_s": interval_s,
                "max_gap_s": max_gap,
                "gap_warning": max_gap > _GAP_WARNING_INTERVALS * interval_s,
                "facts_seen": facts_seen,
            }
        )
    return runs


def run_battery(
    log: HeartbeatLog,
    *,
    workload: str,
    duration_s: float,
    interval_s: float,
    work_interval_s: float,
    work: Callable[[], Any] | None,
    read_facts: Callable[[], dict[str, str]],
    read_system: Callable[[], dict[str, Any]] | None = None,
    static_extra: dict[str, Any] | None = None,
    background_work: bool = False,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Beat every ``interval_s`` until ``duration_s`` (or until the power goes), doing ``work``
    on its own clock. A work item that raises is counted, never the end of the beat."""
    counts = {"done": 0, "failed": 0}
    lock = threading.Lock()

    def one_item() -> None:
        try:
            assert work is not None
            work()
            outcome = "done"
        except Exception:
            outcome = "failed"
        with lock:
            counts[outcome] += 1

    started = clock()
    next_beat = 0.0
    next_work = 0.0
    while True:
        elapsed = clock() - started
        if elapsed >= duration_s:
            break
        if work is not None and elapsed >= next_work:
            next_work += work_interval_s
            if background_work:
                threading.Thread(target=one_item, daemon=True).start()
            else:
                one_item()
        if elapsed >= next_beat:
            next_beat += interval_s
            with lock:
                done, failed = counts["done"], counts["failed"]
            log.append(
                workload=workload,
                extra={
                    **(static_extra or {}),
                    **(read_system() if read_system else {}),
                    "facts": read_facts(),
                    "turns_done": done,
                    "turns_failed": failed,
                },
            )
        upcoming = min(next_beat, next_work) if work is not None else next_beat
        sleep(max(0.0, upcoming - (clock() - started)))
