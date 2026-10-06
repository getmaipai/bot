"""BODY-05: the settle gate over the one funnel.

``SettleGate`` is a filter on what readers are shown, never a second state
machine: the ``ConversationLoop`` still chooses every state. Pure and
clock-injected, so the 0.5 s rule is checked without sleeping.
"""

from __future__ import annotations

import pytest

from maipai_body.presence.funnel import SettleGate

GATE = 0.5


def _gate() -> SettleGate:
    return SettleGate(GATE, initial="idle")


def test_first_change_shows_at_once_because_idle_has_long_held():
    gate = _gate()
    assert gate.offer("listening", 100.0) is True
    assert gate.shown == "listening"
    assert gate.due_in(100.0) is None


def test_a_change_inside_the_gate_is_held_until_the_gate_elapses():
    gate = _gate()
    gate.offer("listening", 0.0)
    assert gate.offer("idle", 0.045) is False  # the 45 ms flash
    assert gate.shown == "listening"
    assert gate.due_in(0.045) == pytest.approx(GATE - 0.045)
    assert gate.flush(0.3) is False
    assert gate.shown == "listening"
    assert gate.flush(GATE) is True
    assert gate.shown == "idle"


def test_the_latest_state_wins_and_unshown_intermediates_are_skipped():
    gate = _gate()
    gate.offer("listening", 0.0)
    gate.offer("thinking", 0.1)
    gate.offer("speaking", 0.2)
    assert gate.flush(GATE) is True
    assert gate.shown == "speaking"


def test_returning_to_the_shown_state_cancels_the_pending_change():
    gate = _gate()
    gate.offer("listening", 0.0)
    gate.offer("thinking", 0.1)
    gate.offer("listening", 0.2)
    assert gate.due_in(0.2) is None
    assert gate.flush(GATE) is False
    assert gate.shown == "listening"


def test_a_state_published_by_flush_starts_its_own_full_hold():
    gate = _gate()
    gate.offer("listening", 0.0)
    gate.offer("thinking", 0.1)
    gate.flush(GATE)  # thinking shown at 0.5
    assert gate.offer("idle", 0.6) is False
    assert gate.flush(0.9) is False
    assert gate.flush(1.0) is True


def _replay(raw: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """Feed raw funnel entries through the gate in time order, landing each
    held change at its due time, and return what readers were shown."""
    gate = _gate()
    shown: list[tuple[float, str]] = []
    queue = list(raw)
    while queue or gate.due_in(0.0) is not None:
        due_at = gate.last_change + GATE if gate.due_in(0.0) is not None else None
        if queue and (due_at is None or queue[0][0] <= due_at):
            at, state = queue.pop(0)
            if gate.offer(state, at):
                shown.append((at, gate.shown))
        elif due_at is not None:
            gate.flush(due_at)
            shown.append((due_at, gate.shown))
    return shown


def test_the_synthetic_flash_trace_never_shows_a_state_shorter_than_the_gate():
    """No legacy trace is available to this repo (legacy-backups is not in the
    clone), so this replays a synthetic one with the same shape: a 45 ms
    listening flash, a fast thinking pass and a short speaking pop."""
    raw = [
        (0.000, "listening"),
        (0.045, "idle"),
        (1.000, "listening"),
        (1.020, "thinking"),
        (1.060, "speaking"),
        (1.110, "idle"),
    ]
    shown = _replay(raw)
    assert [state for _, state in shown] == ["listening", "idle", "listening", "idle"]
    dwell = [b[0] - a[0] for a, b in zip(shown, shown[1:], strict=False)]
    assert min(dwell) >= GATE - 1e-9
