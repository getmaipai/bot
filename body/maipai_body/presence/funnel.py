"""BODY-05: the settle gate over the presence funnel.

The funnel is one state machine and it lives in ``run_loop.py``
(``ConversationLoop``): that is the only place a state is chosen. This
module holds the one thing the funnel's readers need on top of it, the
0.5 s settle gate (the legacy 45 ms flash test): the state *shown* to the
eyes, the mouth, the ring, the screen and the link never changes sooner
than ``hold_s`` after the previous shown change.

A change that arrives inside the hold is kept and lands when the hold
ends. Only the latest pending state lands; an intermediate that never got
its full hold is skipped, never flashed. This is a filter with no states
of its own and no thread: the caller supplies the clock and schedules the
``flush`` the gate says is due.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

_LONG_AGO = float("-inf")


class FunnelState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


@dataclass(frozen=True)
class FunnelView:
    """Everything the funnel's readers (the eyes' director first) are given.

    ``shown`` is the settled state. ``muted``, ``held`` (lifted or carried)
    and ``alarm`` (tipped or in freefall) are separate facts of the same
    funnel, immediate rather than gated: a safety signal never waits.
    """

    shown: FunnelState
    muted: bool = False
    held: bool = False
    alarm: bool = False


class SettleGate[S]:
    def __init__(self, hold_s: float, *, initial: S) -> None:
        if hold_s < 0:
            raise ValueError("hold_s must not be negative")
        self._hold_s = hold_s
        self._shown = initial
        self._pending: S | None = None
        self._last_change = _LONG_AGO

    @property
    def shown(self) -> S:
        return self._shown

    @property
    def last_change(self) -> float:
        """When the shown state last changed (``-inf`` before the first)."""
        return self._last_change

    def offer(self, state: S, now: float) -> bool:
        """The funnel entered ``state``. True when the shown state changed."""
        changed = self.flush(now)
        if state == self._shown:
            self._pending = None
            return changed
        if now - self._last_change >= self._hold_s:
            self._show(state, now)
            return True
        self._pending = state
        return changed

    def flush(self, now: float) -> bool:
        """Land the pending state when its hold is over. True when it landed."""
        pending = self._pending
        if pending is None or now - self._last_change < self._hold_s:
            return False
        self._show(pending, now)
        return True

    def due_in(self, now: float) -> float | None:
        """Seconds until the pending state may land, or ``None`` with nothing held."""
        if self._pending is None:
            return None
        return max(0.0, self._last_change + self._hold_s - now)

    def _show(self, state: S, now: float) -> None:
        self._shown = state
        self._pending = None
        self._last_change = now
