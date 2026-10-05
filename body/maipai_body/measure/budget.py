"""M-R1: the Compute Module's budget, sampled while a turn runs on a clock.

Design record section 12: RSS and headroom, CPU per process, temperature
and throttle flags over an hour, in conversation every two minutes, for
the daemon alone, with the ``pod``-tier body, and with ``stt`` and ``tts``
on the robot. Decision rule: the ``robot`` tier only if endpoint-to-transcript
p95 is under the MaiPai build's M-06 figure plus 500 ms and nothing
throttles. The readers are injected so the suite proves the parsing, the
loop and the rule; the real ``/proc``, thermal zone, ``vcgencmd`` and
``psutil`` are the unit's.
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from maipai_body.measure.stats import summarize

THERMAL_PATH = "/sys/class/thermal/thermal_zone0/temp"
MEMINFO_PATH = "/proc/meminfo"
# The slack the rule allows over the MaiPai build's M-06 figure (design record section 12).
ROBOT_TIER_MARGIN_MS = 500.0
MIN_TURNS_FOR_A_DECISION = 20

# vcgencmd get_throttled bit layout (Raspberry Pi firmware documentation)
_THROTTLED_BITS = {
    0: "under_voltage_now",
    1: "freq_capped_now",
    2: "throttled_now",
    3: "soft_temp_limit_now",
    16: "under_voltage_occurred",
    17: "freq_capped_occurred",
    18: "throttled_occurred",
    19: "soft_temp_limit_occurred",
}
_NOW_MASK = 0b1111


def decode_throttled(value: int) -> dict[str, bool]:
    return {name: bool(value >> bit & 1) for bit, name in _THROTTLED_BITS.items()}


def parse_throttled(text: str) -> int | None:
    """``vcgencmd get_throttled`` prints ``throttled=0x...``; anything else is unreadable."""
    marker = "throttled="
    if marker not in text:
        return None
    try:
        return int(text.split(marker, 1)[1].split()[0], 16)
    except (ValueError, IndexError):
        return None


def parse_thermal_millidegrees(text: str) -> float | None:
    try:
        return int(text.strip()) / 1000.0
    except ValueError:
        return None


def parse_meminfo(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if key in ("MemTotal", "MemAvailable"):
            values[key] = int(rest.split()[0]) / 1024.0
    return {
        "total_mb": values.get("MemTotal", 0.0),
        "available_mb": values.get("MemAvailable", 0.0),
    }


def _read_text(path: str) -> str:
    return Path(path).read_text()


def _run_command(command: Sequence[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, timeout=5, check=False).stdout


class _PsutilProcess:
    """Caches a ``psutil.Process`` so ``cpu_percent`` has a previous reading to diff against."""

    def __init__(self, process) -> None:
        self._process = process
        self.pid = process.pid
        self._process.cpu_percent(interval=None)  # primes the counter

    def cmdline(self) -> list[str]:
        return self._process.cmdline()

    def rss(self) -> int:
        return self._process.memory_info().rss

    def cpu(self) -> float:
        return self._process.cpu_percent(interval=None)


def psutil_lister() -> Callable[[], list[Any]]:
    import os

    import psutil  # a dependency of reachy-mini, present wherever the daemon is

    own_pid = os.getpid()
    cache: dict[int, _PsutilProcess] = {}

    def list_processes() -> list[Any]:
        live = set()
        for process in psutil.process_iter():
            if process.pid == own_pid:
                continue  # the measurement is not part of what it measures
            live.add(process.pid)
            if process.pid not in cache:
                try:
                    cache[process.pid] = _PsutilProcess(process)
                except psutil.Error:
                    continue
        for gone in set(cache) - live:
            del cache[gone]
        return list(cache.values())

    return list_processes


class BudgetSampler:
    def __init__(
        self,
        *,
        processes: dict[str, str],
        list_processes: Callable[[], list[Any]],
        read_text: Callable[[str], str] = _read_text,
        run_command: Callable[[Sequence[str]], str] = _run_command,
    ) -> None:
        self._patterns = processes
        self._list = list_processes
        self._read_text = read_text
        self._run = run_command

    def _process_figures(self) -> dict[str, dict[str, Any] | None]:
        procs = self._list()
        figures: dict[str, dict[str, Any] | None] = {}
        for name, pattern in self._patterns.items():
            matched = []
            for proc in procs:
                try:
                    cmdline = " ".join(proc.cmdline())
                    if any(alternative in cmdline for alternative in pattern.split("|")):
                        matched.append(proc)
                except Exception:
                    continue
            if not matched:
                figures[name] = None
                continue
            figures[name] = {
                "pids": [p.pid for p in matched],
                "rss_mb": sum(p.rss() for p in matched) / 2**20,
                "cpu_pct": sum(p.cpu() for p in matched),
            }
        return figures

    def sample(self, *, t_s: float) -> dict[str, Any]:
        try:
            temp_c = parse_thermal_millidegrees(self._read_text(THERMAL_PATH))
        except OSError:
            temp_c = None
        try:
            mem = parse_meminfo(self._read_text(MEMINFO_PATH))
            mem_available_mb: float | None = mem["available_mb"]
        except OSError:
            mem_available_mb = None
        try:
            raw = parse_throttled(self._run(["vcgencmd", "get_throttled"]))
        except (OSError, subprocess.SubprocessError):
            raw = None
        return {
            "t_s": t_s,
            "processes": self._process_figures(),
            "temp_c": temp_c,
            "mem_available_mb": mem_available_mb,
            "throttled_raw": raw,
            "throttled_now": None if raw is None else bool(raw & _NOW_MASK),
        }


def run_budget(
    sampler: BudgetSampler,
    *,
    duration_s: float,
    interval_s: float,
    turn_interval_s: float,
    run_turn: Callable[[], dict[str, Any]],
    background_turns: bool = False,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sample every ``interval_s`` for ``duration_s``, a turn every ``turn_interval_s``.

    ``background_turns`` runs each turn on its own thread so a multi-second
    turn does not stall the sampling clock (the real run); a turn that
    raises is a failed turn row, never the end of the run.
    """
    samples: list[dict[str, Any]] = []
    turn_rows: list[dict[str, Any]] = []
    workers: list[threading.Thread] = []
    lock = threading.Lock()

    def one_turn() -> None:
        try:
            row = run_turn()
        except Exception as exc:
            row = {"error": f"{type(exc).__name__}: {exc}"}
        with lock:
            turn_rows.append(row)

    started = clock()
    next_sample = 0.0
    next_turn = 0.0
    while True:
        elapsed = clock() - started
        if elapsed >= duration_s:
            break
        if elapsed >= next_turn:
            next_turn += turn_interval_s
            if background_turns:
                worker = threading.Thread(target=one_turn, daemon=True)
                worker.start()
                workers.append(worker)
            else:
                one_turn()
        if elapsed >= next_sample:
            samples.append(sampler.sample(t_s=round(elapsed, 3)))
            next_sample += interval_s
        sleep(max(0.0, min(next_sample, next_turn) - (clock() - started)))
    for worker in workers:
        worker.join(timeout=120.0)
    return samples, turn_rows


def summarize_budget(samples: list[dict[str, Any]], turns: list[dict[str, Any]]) -> dict[str, Any]:
    names = sorted({name for s in samples for name in s["processes"]})
    processes: dict[str, Any] = {}
    for name in names:
        seen = [s["processes"][name] for s in samples if s["processes"].get(name)]
        processes[name] = {
            "samples": len(seen),
            "rss_mb_max": max((p["rss_mb"] for p in seen), default=None),
            "cpu_pct": summarize([p["cpu_pct"] for p in seen]),
        }
    temps = [s["temp_c"] for s in samples if s["temp_c"] is not None]
    available = [s["mem_available_mb"] for s in samples if s["mem_available_mb"] is not None]
    raws = [s["throttled_raw"] for s in samples if s["throttled_raw"] is not None]
    ok_turns = [t for t in turns if "error" not in t]
    figure_keys = sorted({k for t in ok_turns for k in t if k.endswith("_ms")})
    ever = 0
    for raw in raws:
        ever |= raw
    return {
        "samples": len(samples),
        "processes": processes,
        "temp_c_max": max(temps, default=None),
        "mem_available_mb_min": min(available, default=None),
        "throttled": {
            "samples_throttled_now": sum(1 for s in samples if s["throttled_now"]),
            "ever_flagged_bits": ever,
        },
        "turns": {
            "n": len(turns),
            "failed": len(turns) - len(ok_turns),
            **{
                key: summarize([t[key] for t in ok_turns if t.get(key) is not None])
                for key in figure_keys
            },
        },
    }


def robot_tier_decision(
    *, endpoint_to_transcript_p95_ms: float, m06_p95_ms: float, any_throttle: bool, turns: int
) -> dict[str, Any]:
    """Section 12's rule: adopt only if p95 is under M-06 plus 500 ms and nothing throttled."""
    limit = m06_p95_ms + ROBOT_TIER_MARGIN_MS
    if turns < MIN_TURNS_FOR_A_DECISION:
        return {
            "adopt": False,
            "limit_ms": limit,
            "reason": f"inconclusive: {turns} turns, the rule wants at least "
            f"{MIN_TURNS_FOR_A_DECISION}",
        }
    if any_throttle:
        return {"adopt": False, "limit_ms": limit, "reason": "the run throttled"}
    if not endpoint_to_transcript_p95_ms < limit:
        return {
            "adopt": False,
            "limit_ms": limit,
            "reason": f"p95 {endpoint_to_transcript_p95_ms:.0f} ms is not under {limit:.0f} ms",
        }
    return {
        "adopt": True,
        "limit_ms": limit,
        "reason": (
            f"p95 {endpoint_to_transcript_p95_ms:.0f} ms is under {limit:.0f} ms, no throttle"
        ),
    }
