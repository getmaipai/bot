"""M-R3: wake and direction of arrival on this array.

Design record section 12: the wake model on the daemon's 16 kHz path (false
accepts per hour, recall), direction-of-arrival error at eight bearings, and
barge-in through the chip's echo cancellation with speech playing at
conversation level. The gates are ``dev.md`` section 11's (M-08's): at most
one false accept per two hours at room level, at least nine wakes in ten at
one meter quiet and eight in ten at three meters with a television on, the
near-miss set never waking. The scoring loops take the capture and the
scorer they are given, so the suite proves them against scripted audio and
the unit runs them against the real array and model.
"""

from __future__ import annotations

import math
import statistics
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

from maipai_body.hal.seam import DirectionOfArrival
from maipai_body.measure.stats import summarize

_POLL_SLEEP_S = 0.01
MIN_LISTENED_HOURS_FOR_FALSE_ACCEPTS = 2.0
MAX_FALSE_ACCEPTS_PER_HOUR = 0.5
MIN_RECALL_ATTEMPTS = 10
RECALL_QUIET_1M = 0.9
RECALL_TV_3M = 0.8


def eight_bearings() -> list[float]:
    """Bearings in radians, 45 degrees apart; 0 is straight ahead, positive is the robot's left."""
    return [i * math.pi / 4 for i in range(8)]


def expected_array_angle(bearing_rad: float) -> float:
    """The array angle a source at ``bearing_rad`` should read.

    The SDK documents the array's angle as 0 rad at the robot's left, pi/2
    in front or behind, pi at its right, so a source ahead and its mirror
    behind read alike. The error is therefore taken in array-angle space,
    where front and back are one; the per-bearing raw readings are kept so
    a wrong convention shows up in the first run rather than hiding in a
    summary.
    """
    return math.pi / 2 - math.asin(math.sin(bearing_rad))


def summarize_bearing(readings: Sequence[DirectionOfArrival], bearing_rad: float) -> dict[str, Any]:
    speech = [r.angle_rad for r in readings if r.speech_detected]
    expected = expected_array_angle(bearing_rad)
    return {
        "bearing_deg": round(math.degrees(bearing_rad), 3),
        "expected_array_rad": expected,
        "readings": len(readings),
        "speech_readings": len(speech),
        "median_measured_rad": statistics.median(speech) if speech else None,
        "error_deg": summarize([math.degrees(abs(angle - expected)) for angle in speech]),
    }


def collect_doa(
    audio, *, dwell_s: float, hz: float, sleep: Callable[[float], None] = time.sleep
) -> list[DirectionOfArrival]:
    """Poll the array for ``dwell_s`` at ``hz``; a poll it cannot answer is skipped."""
    readings: list[DirectionOfArrival] = []
    for _ in range(round(dwell_s * hz)):
        reading = audio.get_doa()
        if reading is not None:
            readings.append(reading)
        sleep(1.0 / hz)
    return readings


def listen_for_wake(
    capture,
    scorer,
    *,
    window_s: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Score the live capture for ``window_s``; did the wake word fire, how fast, how near."""
    started = clock()
    best = 0.0
    while clock() - started < window_s:
        blocks = capture.poll_blocks()
        for block in blocks:
            event = scorer.poll(block)
            best = max(best, scorer.last_score)
            if event is not None:
                return {"fired": True, "delay_s": clock() - started, "best_score": best}
        if not blocks:
            sleep(_POLL_SLEEP_S)
    return {"fired": False, "delay_s": None, "best_score": best}


def count_false_accepts(
    capture,
    scorer,
    *,
    duration_s: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Score ambient audio for ``duration_s``; with no one asked to speak, every wake is false."""
    started = clock()
    events: list[float] = []
    while clock() - started < duration_s:
        blocks = capture.poll_blocks()
        for block in blocks:
            if scorer.poll(block) is not None:
                events.append(clock() - started)
        if not blocks:
            sleep(_POLL_SLEEP_S)
    return {"events_s": events, "duration_s": clock() - started}


def evaluate_wake_gates(
    *,
    false_accepts: int,
    listened_hours: float,
    recall_quiet_1m: tuple[int, int],
    recall_tv_3m: tuple[int, int],
    near_miss: tuple[int, int],
) -> dict[str, dict[str, Any]]:
    """The M-08 gates over what the run recorded; ``pass`` is ``None`` when it cannot decide."""

    def recall(hits_n: tuple[int, int], threshold: float, text: str) -> dict[str, Any]:
        hits, n = hits_n
        if n < MIN_RECALL_ATTEMPTS:
            return {
                "pass": None,
                "gate": text,
                "value": f"{hits}/{n}",
                "note": f"needs at least {MIN_RECALL_ATTEMPTS} attempts to decide",
            }
        return {"pass": hits / n >= threshold, "gate": text, "value": f"{hits}/{n}"}

    if listened_hours < MIN_LISTENED_HOURS_FOR_FALSE_ACCEPTS:
        false_gate: dict[str, Any] = {
            "pass": None,
            "gate": "at most one false accept per 2 hours at room level",
            "value": f"{false_accepts} in {listened_hours:.2f} h",
            "note": "needs at least 2 hours listened to decide",
        }
    else:
        false_gate = {
            "pass": false_accepts / listened_hours <= MAX_FALSE_ACCEPTS_PER_HOUR,
            "gate": "at most one false accept per 2 hours at room level",
            "value": f"{false_accepts} in {listened_hours:.2f} h",
        }
    wakes, tried = near_miss
    near_miss_gate: dict[str, Any] = {
        "pass": None if tried < MIN_RECALL_ATTEMPTS else wakes == 0,
        "gate": "the near-miss set never wakes",
        "value": f"{wakes}/{tried} woke",
    }
    if tried < MIN_RECALL_ATTEMPTS:
        near_miss_gate["note"] = f"needs at least {MIN_RECALL_ATTEMPTS} attempts to decide"
    return {
        "false_accepts": false_gate,
        "recall_quiet_1m": recall(
            recall_quiet_1m, RECALL_QUIET_1M, "at least 9 in 10 at 1 m, quiet"
        ),
        "recall_tv_3m": recall(
            recall_tv_3m, RECALL_TV_3M, "at least 8 in 10 at 3 m, television on"
        ),
        "near_miss": near_miss_gate,
    }


def play_samples(
    playback,
    samples: npt.NDArray[np.float32],
    rate: int,
    *,
    chunk_s: float,
    stop: threading.Event,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Push ``samples`` to the speaker in real-time-paced chunks until done or ``stop``."""
    chunk = int(rate * chunk_s)
    for start in range(0, len(samples), chunk):
        if stop.is_set():
            return
        playback.push(samples[start : start + chunk])
        sleep(chunk_s)


def assemble_parts(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Gather the per-part run files into the report's shape and evaluate the gates.

    A part that was not run leaves its gate undecided; it is never counted
    as a pass or a failure.
    """
    if not rows:
        raise ValueError("no M-R3 part rows to assemble")
    parts: dict[str, Any] = {}
    for row in rows:
        kind = row["part"]
        if kind == "recall":
            parts.setdefault("recall", []).append(row)
        elif kind == "doa":
            parts["doa"] = row["bearings"]
        else:
            parts[kind] = row
    recall = {r["condition"]: (r["hits"], r["attempts"]) for r in parts.get("recall", [])}
    false_accepts = parts.get("false_accepts")
    parts["gates"] = evaluate_wake_gates(
        false_accepts=false_accepts["events"] if false_accepts else 0,
        listened_hours=false_accepts["listened_hours"] if false_accepts else 0.0,
        recall_quiet_1m=recall.get("quiet_1m", (0, 0)),
        recall_tv_3m=recall.get("tv_3m", (0, 0)),
        near_miss=recall.get("near_miss", (0, 0)),
    )
    return parts
