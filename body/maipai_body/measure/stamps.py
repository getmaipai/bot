"""Motion onset stamps on one monotonic clock (``dev.md`` section 5, Timing).

The run loop gets one injected ``StampSink``; the default is
``NullSink``, so an unmeasured run pays nothing. ``StampRecorder`` is the
sink a bench passes: it keeps first-wins stamps per cue, counts what
section 5's negative rows name (a dropped, duplicated or late cue, a
socket loss, a hub stamp that disagrees), and derives each row's legs.

Every local stamp is ``time.monotonic_ns`` on the one machine. A hub
stamp is on another clock: it is recorded beside the row, compared only
as an interval, and never used for ordering.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from maipai_body.measure.stats import summarize

STAMP_NAMES = (
    "t_heard",
    "t_cue_emitted",
    "t_cue_received",
    "t_motion_command",
    "t_encoder_onset",
    "t_first_audio_out",
    "t_acoustic_onset",
)
# Cue to command, measured in the body from t_cue_received (dev.md section 5).
COMMAND_P95_BUDGET_MS = 50.0
# The reasons that may legitimately withhold an eligible primitive: the
# body's own physical and service state (the suppression column of the
# primitive table). Policy reasons (a guard, a defer, a companion's
# playfulness rule) make a row ineligible before it is measured; they are
# not a bench excuse.
SAFETY_SUPPRESSIONS = frozenset(
    {"near_hand", "service_mode", "dock_transition", "thermal_pressure", "stale_track"}
)
# How far the hub's own heard-to-emitted interval may differ from the local
# one before the row says they disagree. A starting value for the first
# connected-mode run to confirm.
HUB_INTERVAL_TOLERANCE_MS = 5.0

# stamps that open a cue's row; a cue whose turn is already closed is late
_LIFECYCLE = ("t_cue_emitted", "t_cue_received", "t_motion_command")


@dataclass(frozen=True)
class CueId:
    turn_id: str
    seq: int


@runtime_checkable
class StampSink(Protocol):
    """What the run loop, the runtime socket and the playback path call."""

    def stamp(self, cue_id: CueId, name: str, t_ns: int | None = None) -> None: ...

    def hub_stamp(self, cue_id: CueId, name: str, value_ns: int) -> None: ...

    def suppressed(self, cue_id: CueId, reason: str, *, condition_present: bool) -> None: ...

    def close_turn(self, turn_id: str, reason: str) -> None: ...

    def socket_lost(self) -> None: ...


class NullSink:
    def stamp(self, cue_id: CueId, name: str, t_ns: int | None = None) -> None:
        pass

    def hub_stamp(self, cue_id: CueId, name: str, value_ns: int) -> None:
        pass

    def suppressed(self, cue_id: CueId, reason: str, *, condition_present: bool) -> None:
        pass

    def close_turn(self, turn_id: str, reason: str) -> None:
        pass

    def socket_lost(self) -> None:
        pass


def _ms(later: int | None, earlier: int | None) -> float | None:
    if later is None or earlier is None:
        return None
    return (later - earlier) / 1e6


@dataclass
class StampRow:
    cue_id: CueId
    stamps: dict[str, int] = field(default_factory=dict)
    hub: dict[str, int] = field(default_factory=dict)
    duplicates: int = 0
    late: bool = False
    socket_lost: bool = False
    late_moved: bool = False
    suppression: tuple[str, bool] | None = None

    @property
    def status(self) -> str:
        if self.socket_lost:
            return "socket_lost"
        if self.late:
            return "late"
        if self.suppression is not None:
            return "suppressed"
        if "t_cue_emitted" in self.stamps and "t_cue_received" not in self.stamps:
            return "dropped"
        return "complete"

    @property
    def socket_leg_ms(self) -> float | None:
        return _ms(self.stamps.get("t_cue_received"), self.stamps.get("t_cue_emitted"))

    @property
    def cue_to_command_ms(self) -> float | None:
        return _ms(self.stamps.get("t_motion_command"), self.stamps.get("t_cue_received"))

    @property
    def cue_to_onset_ms(self) -> float | None:
        return _ms(self.stamps.get("t_encoder_onset"), self.stamps.get("t_cue_received"))

    @property
    def cue_to_acoustic_ms(self) -> float | None:
        return _ms(self.stamps.get("t_acoustic_onset"), self.stamps.get("t_cue_received"))

    @property
    def output_latency_ms(self) -> float | None:
        return _ms(self.stamps.get("t_acoustic_onset"), self.stamps.get("t_first_audio_out"))

    @property
    def onset_before_acoustic(self) -> bool | None:
        """The ordering result, always against the sound that left the speaker."""
        encoder = self.stamps.get("t_encoder_onset")
        acoustic = self.stamps.get("t_acoustic_onset")
        if encoder is None or acoustic is None:
            return None
        return encoder < acoustic

    @property
    def hub_disagrees(self) -> bool | None:
        """Whether the hub's heard-to-emitted interval differs from the local one.

        Offsets between the clocks cancel in an interval; the hub's absolute
        stamps are never compared to local ones.
        """
        hub = _ms(self.hub.get("t_cue_emitted"), self.hub.get("t_heard"))
        local = _ms(self.stamps.get("t_cue_emitted"), self.stamps.get("t_heard"))
        if hub is None or local is None:
            return None
        return hub < 0 or abs(hub - local) > HUB_INTERVAL_TOLERANCE_MS

    @property
    def failure(self) -> str | None:
        if self.late_moved:
            return "a cue after its turn closed reached the motion path"
        if self.suppression is not None:
            reason, present = self.suppression
            if reason not in SAFETY_SUPPRESSIONS:
                return f"suppressed for {reason!r}, which is not a listed safety reason"
            if not present:
                return f"suppressed for {reason!r} but the condition was not present"
            return None
        if self.onset_before_acoustic is False:
            return "motion onset did not precede the acoustic onset"
        return None


class StampRecorder:
    def __init__(self, clock: Callable[[], int] = time.monotonic_ns) -> None:
        self._clock = clock
        self._rows: dict[CueId, StampRow] = {}
        self._closed: set[str] = set()

    def _row(self, cue_id: CueId) -> StampRow:
        return self._rows.setdefault(cue_id, StampRow(cue_id))

    def stamp(self, cue_id: CueId, name: str, t_ns: int | None = None) -> None:
        if name not in STAMP_NAMES:
            raise ValueError(f"unknown stamp {name!r}; the names are {STAMP_NAMES}")
        now = self._clock() if t_ns is None else t_ns
        known = cue_id in self._rows
        row = self._row(cue_id)
        if not known and name in _LIFECYCLE:
            if cue_id.turn_id in self._closed:
                row.late = True
                return
        if row.socket_lost or (row.late and name in _LIFECYCLE):
            if name == "t_motion_command":
                row.late_moved = row.late
            return
        if name in row.stamps:
            row.duplicates += 1
            return
        row.stamps[name] = now

    def hub_stamp(self, cue_id: CueId, name: str, value_ns: int) -> None:
        if name not in STAMP_NAMES:
            raise ValueError(f"unknown stamp {name!r}; the names are {STAMP_NAMES}")
        self._row(cue_id).hub.setdefault(name, value_ns)

    def suppressed(self, cue_id: CueId, reason: str, *, condition_present: bool) -> None:
        self._row(cue_id).suppression = (reason, condition_present)

    def close_turn(self, turn_id: str, reason: str) -> None:
        self._closed.add(turn_id)

    def socket_lost(self) -> None:
        """Every cue that never arrived is lost and its turn closed, so a late
        arrival is dropped. Cues that arrived keep their rows; a new turn after
        a reconnect starts clean."""
        for row in self._rows.values():
            if "t_cue_received" not in row.stamps and "t_cue_emitted" in row.stamps:
                row.socket_lost = True
        self._closed.update(row.cue_id.turn_id for row in self._rows.values())

    def rows(self) -> list[StampRow]:
        return list(self._rows.values())


def summarize_rows(rows: Iterable[StampRow]) -> dict[str, Any]:
    """Counts per outcome and p50 and p95 per leg; never a mean, never a zero for nothing.

    A dropped, late or socket-lost row has no leg to report and stays out
    of the percentiles; it is counted instead.
    """
    rows = list(rows)
    measured = [r for r in rows if r.status in ("complete", "suppressed")]

    def leg(name: str) -> dict[str, float | int | None]:
        values = [getattr(r, name) for r in measured]
        return summarize([v for v in values if v is not None])

    command = leg("cue_to_command_ms")
    p95 = command["p95"]
    return {
        "rows": len(rows),
        "complete": sum(1 for r in rows if r.status == "complete"),
        "dropped": sum(1 for r in rows if r.status == "dropped"),
        "late": sum(1 for r in rows if r.status == "late"),
        "socket_lost": sum(1 for r in rows if r.status == "socket_lost"),
        "suppressed": sum(1 for r in rows if r.status == "suppressed"),
        "duplicates": sum(r.duplicates for r in rows),
        "hub_disagreements": sum(1 for r in rows if r.hub_disagrees),
        "failed": sum(1 for r in rows if r.failure is not None),
        "ordering_failures": sum(1 for r in rows if r.onset_before_acoustic is False),
        "socket_leg_ms": leg("socket_leg_ms"),
        "cue_to_command_ms": command,
        "cue_to_onset_ms": leg("cue_to_onset_ms"),
        "cue_to_acoustic_ms": leg("cue_to_acoustic_ms"),
        "output_latency_ms": leg("output_latency_ms"),
        "command_within_budget": None if p95 is None else p95 < COMMAND_P95_BUDGET_MS,
    }
