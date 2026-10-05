"""LINK-STATE-01: the supervisor drives the walk and the cues on an injected clock."""

from __future__ import annotations

from maipai_body.link.address_walk import HubEndpoint, PathKind
from maipai_body.link.discovery import HubAddress
from maipai_body.link.lifecycle import LinkLifecycle
from maipai_body.link.state_machine import LinkPhase, LinkStateMachine
from maipai_body.link.store import PairingStore
from maipai_body.link.supervisor import LinkSupervisor, SupervisorSettings
from tests.ladder_fakes import FakeClock
from tests.test_link_lifecycle import _result
from tests.test_link_lifecycle_ladder import _AddressClient

SETTINGS = SupervisorSettings(reconnect_interval_s=30.0, sleeping_interval_s=300.0)
N = 600.0


def _rig(reconnect):
    clock = FakeClock()
    machine = LinkStateMachine(clock=clock, wall_clock=clock.wall_clock, sleep_after_s=N)
    supervisor = LinkSupervisor(
        machine=machine, reconnect=reconnect, clock=clock, settings=SETTINGS
    )
    return supervisor, machine, clock


def test_nothing_is_walked_while_connected():
    calls = []
    supervisor, machine, clock = _rig(lambda: calls.append(1) or False)
    clock.advance(1000)
    supervisor.step()
    assert calls == []


def test_it_walks_at_once_on_loss_then_every_reconnect_interval():
    calls = []
    supervisor, machine, clock = _rig(lambda: calls.append(clock.now) or False)
    machine.link_lost("x")
    supervisor.step()
    assert len(calls) == 1
    clock.advance(29)
    supervisor.step()
    assert len(calls) == 1
    clock.advance(1)
    supervisor.step()
    assert len(calls) == 2


def test_it_reaches_sleeping_only_after_n_and_then_walks_slowly():
    calls = []
    supervisor, machine, clock = _rig(lambda: calls.append(clock.now) or False)
    machine.link_lost("x")
    for _ in range(int(N // 30) - 1):  # 19 steps: 570 s
        supervisor.step()
        clock.advance(30)
    supervisor.step()  # at 570 s
    assert machine.phase is LinkPhase.RECONNECTING
    clock.advance(30)
    supervisor.step()  # at 600 s
    assert machine.phase is LinkPhase.SLEEPING
    before = len(calls)
    clock.advance(299)
    supervisor.step()
    assert len(calls) == before
    clock.advance(1)
    supervisor.step()
    assert len(calls) == before + 1


def test_a_walk_that_raises_is_a_failed_redeem_not_a_dead_supervisor():
    def boom():
        raise RuntimeError("socket gone")

    supervisor, machine, clock = _rig(boom)
    machine.link_lost("x")
    supervisor.step()
    assert machine.snapshot().last_error == "walk failed: RuntimeError"
    assert machine.phase is LinkPhase.RECONNECTING


def test_a_due_timer_fires_its_callback_once():
    from maipai_body.link.commands import LocalTimers

    fired = []
    clock = FakeClock()
    machine = LinkStateMachine(clock=clock, wall_clock=clock.wall_clock)
    timers = LocalTimers(clock)
    supervisor = LinkSupervisor(
        machine=machine,
        reconnect=lambda: False,
        clock=clock,
        timers=timers,
        on_timer_due=lambda: fired.append(1),
    )
    timers.start(10)
    supervisor.step()
    assert fired == []
    clock.advance(10)
    supervisor.step()
    supervisor.step()
    assert fired == [1]


def test_end_to_end_a_real_lifecycle_walk_returns_the_machine_to_connected(tmp_path):
    clock = FakeClock()
    machine = LinkStateMachine(clock=clock, wall_clock=clock.wall_clock, sleep_after_s=N)
    tailnet = HubEndpoint(PathKind.TAILNET, "http://hub.tail1.ts.net:80", "tailnet")
    client = _AddressClient(answering=set())
    store = PairingStore(tmp_path / "pairing.json")
    store.save(_result().pairing)
    link = LinkLifecycle(
        store,
        client,
        discover=lambda timeout_s: HubAddress(
            host="192.0.2.77", port=80, instance_id="hub-test", name="Hub", tls=False
        ),
        observer=machine,
        address_walk=True,
        tailnet=lambda: [tailnet],
    )
    supervisor = LinkSupervisor(
        machine=machine, reconnect=link.reconnect_once, clock=clock, settings=SETTINGS
    )

    machine.link_lost("the turn stream dropped")
    supervisor.step()
    assert machine.phase is LinkPhase.RECONNECTING
    assert client.refreshed_at == [
        "http://192.0.2.10:80",
        "http://192.0.2.77:80",
        tailnet.base_url,
    ]
    snap = machine.snapshot()
    assert snap.attempts == 3
    assert snap.last_error == "unreachable: ConnectTimeout"

    client.answering = {tailnet.base_url}
    clock.advance(30)
    supervisor.step()
    assert machine.phase is LinkPhase.CONNECTED
    assert machine.snapshot().answered_path == "tailnet"
