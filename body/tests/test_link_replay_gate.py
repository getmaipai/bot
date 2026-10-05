"""LINK-STATE-01: the queue rule and the replay rule."""

from __future__ import annotations

from maipai_body.link.replay import ConfirmationEvent, ReplayGate, ReplayItem, ToolCall


def _gate(*, accepting: bool):
    ran: list[str] = []
    return ReplayGate(lambda item: ran.append(item.item_id), accepting=accepting), ran


def test_with_queueing_off_nothing_is_kept_and_the_refusals_are_counted():
    gate, ran = _gate(accepting=False)
    assert gate.offer(ReplayItem("a", "turn the lamp on", ToolCall("lamp.set", "write"))) is False
    assert gate.pending == ()
    assert gate.refused == 1
    assert ran == []


def test_a_replay_fixture_holding_a_write_tool_does_not_run_it_until_confirmed():
    gate, ran = _gate(accepting=True)
    gate.offer(ReplayItem("w1", "turn the lamp on", ToolCall("lamp.set", "write")))
    gate.begin_replay()
    assert ran == []
    gate.handle(ConfirmationEvent("someone-else"))
    assert ran == []
    gate.handle(ConfirmationEvent("w1"))
    assert ran == ["w1"]
    gate.handle(ConfirmationEvent("w1"))
    assert ran == ["w1"]  # a confirmation runs it once


def test_a_physical_tool_needs_confirmation_too_and_so_does_plain_text():
    gate, ran = _gate(accepting=True)
    gate.offer(ReplayItem("p1", "wave", ToolCall("body.wave", "physical")))
    gate.offer(ReplayItem("t1", "what was the score", None))
    gate.begin_replay()
    assert ran == []
    gate.handle(ConfirmationEvent("t1"))
    gate.handle(ConfirmationEvent("p1"))
    assert ran == ["t1", "p1"]
