"""LINK-STATE-01: the connected, reconnecting, sleeping machine, on an injected clock."""

from __future__ import annotations

from maipai_body.link.state_machine import (
    LADDER_ACTIVITIES,
    LinkPhase,
    LinkStateMachine,
)
from tests.ladder_fakes import FakeClock

N_MINUTES = 7


def _machine(clock: FakeClock) -> tuple[LinkStateMachine, list[tuple[LinkPhase, LinkPhase]]]:
    machine = LinkStateMachine(
        clock=clock, wall_clock=clock.wall_clock, sleep_after_s=N_MINUTES * 60.0
    )
    seen: list[tuple[LinkPhase, LinkPhase]] = []
    machine.subscribe(lambda old, new: seen.append((old, new)))
    return machine, seen


def test_it_starts_connected():
    machine, _ = _machine(FakeClock())
    assert machine.phase is LinkPhase.CONNECTED


def test_the_phase_values_are_the_spec_activity_values():
    assert {p.value for p in LinkPhase} == {"connected", "reconnecting", "sleeping"}
    assert LADDER_ACTIVITIES == frozenset({"reconnecting", "sleeping"})


def test_link_lost_moves_connected_to_reconnecting():
    machine, seen = _machine(FakeClock())
    machine.link_lost("the turn stream dropped")
    assert machine.phase is LinkPhase.RECONNECTING
    assert seen == [(LinkPhase.CONNECTED, LinkPhase.RECONNECTING)]
    assert machine.snapshot().last_error == "the turn stream dropped"


def test_a_failed_re_redeem_does_the_same():
    machine, seen = _machine(FakeClock())
    machine.redeem_failed("unreachable: ConnectTimeout")
    assert machine.phase is LinkPhase.RECONNECTING
    assert seen == [(LinkPhase.CONNECTED, LinkPhase.RECONNECTING)]
    assert machine.snapshot().last_error == "unreachable: ConnectTimeout"


def test_it_sleeps_only_after_n_injected_minutes_and_not_before():
    clock = FakeClock()
    machine, seen = _machine(clock)
    machine.link_lost("x")
    clock.advance(N_MINUTES * 60.0 - 1.0)
    machine.tick()
    assert machine.phase is LinkPhase.RECONNECTING
    clock.advance(1.0)
    machine.tick()
    assert machine.phase is LinkPhase.SLEEPING
    assert seen[-1] == (LinkPhase.RECONNECTING, LinkPhase.SLEEPING)


def test_a_second_loss_does_not_restart_the_sleep_clock():
    clock = FakeClock()
    machine, _ = _machine(clock)
    machine.link_lost("first")
    clock.advance(N_MINUTES * 60.0 - 10.0)
    machine.redeem_failed("second")
    clock.advance(10.0)
    machine.tick()
    assert machine.phase is LinkPhase.SLEEPING
    assert machine.snapshot().last_error == "second"


def test_a_loss_while_sleeping_stays_sleeping():
    clock = FakeClock()
    machine, seen = _machine(clock)
    machine.link_lost("x")
    clock.advance(N_MINUTES * 60.0)
    machine.tick()
    machine.link_lost("again")
    assert machine.phase is LinkPhase.SLEEPING
    assert len(seen) == 2


def test_a_redeem_from_reconnecting_returns_to_connected():
    machine, seen = _machine(FakeClock())
    machine.link_lost("x")
    machine.redeemed("lan", "http://192.0.2.10:80")
    assert machine.phase is LinkPhase.CONNECTED
    assert seen[-1] == (LinkPhase.RECONNECTING, LinkPhase.CONNECTED)


def test_a_redeem_from_sleeping_returns_to_connected():
    clock = FakeClock()
    machine, seen = _machine(clock)
    machine.link_lost("x")
    clock.advance(N_MINUTES * 60.0)
    machine.tick()
    machine.redeemed("tailnet", "http://hub.tail1.ts.net:80")
    assert machine.phase is LinkPhase.CONNECTED
    assert seen[-1] == (LinkPhase.SLEEPING, LinkPhase.CONNECTED)


def test_a_redeem_while_connected_notifies_nobody_but_records_contact():
    clock = FakeClock()
    machine, seen = _machine(clock)
    machine.redeemed("lan", "http://192.0.2.10:80")
    assert seen == []
    assert machine.snapshot().last_connected_wall == clock.wall
    assert machine.snapshot().answered_path == "lan"


def test_the_snapshot_carries_the_walk_values_and_resets_per_outage():
    clock = FakeClock()
    machine, _ = _machine(clock)
    machine.redeemed("lan", "http://192.0.2.10:80")
    contact = clock.wall
    clock.advance(30.0)
    machine.link_lost("boom")
    machine.attempt("http://192.0.2.10:80")
    machine.attempt("http://hub.tail1.ts.net:80")
    snap = machine.snapshot()
    assert snap.phase is LinkPhase.RECONNECTING
    assert snap.attempts == 2
    assert snap.current_address == "http://hub.tail1.ts.net:80"
    assert snap.last_connected_wall == contact
    assert snap.answered_path == "lan"
    machine.redeemed("tailnet", "http://hub.tail1.ts.net:80")
    machine.link_lost("again")
    assert machine.snapshot().attempts == 0
    assert machine.snapshot().answered_path == "tailnet"


def test_a_listener_that_raises_does_not_break_the_machine():
    machine, _ = _machine(FakeClock())

    def boom(old, new):
        raise RuntimeError("listener bug")

    machine.subscribe(boom)
    machine.link_lost("x")
    assert machine.phase is LinkPhase.RECONNECTING
