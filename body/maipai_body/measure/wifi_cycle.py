"""M-R5 on the unit: cycle the real radio and time the way back.

Only the unit has a Wi-Fi link to lose. The commands that switch the radio
are the operator's to name (``nmcli radio wifi off`` and ``on`` on the
image, or whatever the unit's network stack wants); this module only
sequences them around a timed probe of the hub, and always runs the "on"
command, whatever happens in between.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from typing import Any


def run_shell(command: str) -> None:
    subprocess.run(command, shell=True, check=False, timeout=60)


def time_to_reachable(
    probe: Callable[[], bool],
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    interval_s: float = 0.2,
    timeout_s: float = 120.0,
) -> float | None:
    """Milliseconds until ``probe`` first succeeds, or ``None`` past ``timeout_s``.

    A probe that raises counts as unreachable: while the radio is coming
    back, "network unreachable" is the expected answer, not a failure.
    """
    started = clock()
    while clock() - started < timeout_s:
        try:
            if probe():
                return (clock() - started) * 1e3
        except Exception:
            pass
        sleep(interval_s)
    return None


def run_wifi_cycle_trial(
    *,
    off_command: str,
    on_command: str,
    outage_s: float,
    probe: Callable[[], bool],
    runner: Callable[[str], Any] = run_shell,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    interval_s: float = 0.2,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    runner(off_command)
    try:
        sleep(outage_s)
    finally:
        runner(on_command)
    return {
        "outage_s": outage_s,
        "reachable_after_ms": time_to_reachable(
            probe, clock=clock, sleep=sleep, interval_s=interval_s, timeout_s=timeout_s
        ),
    }
