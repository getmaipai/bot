"""LINK-STATE-01: LinkLifecycle reports every redeem to the ladder and can
walk the address book instead of retrying one address."""

from __future__ import annotations

import threading

from maipai_body.link.address_walk import HubEndpoint, PathKind
from maipai_body.link.discovery import HubAddress
from maipai_body.link.lifecycle import LinkLifecycle
from maipai_body.link.store import PairingStore
from tests.test_link_lifecycle import _FakeClient, _result, _run_until


class _Observer:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def attempt(self, address: str) -> None:
        self.events.append(("attempt", address))

    def redeemed(self, path: str, address: str | None = None) -> None:
        self.events.append(("redeemed", path, address))

    def redeem_failed(self, error: str) -> None:
        self.events.append(("failed", error))


class _AddressClient(_FakeClient):
    """The fake, plus the per-address redeem the walk uses."""

    def __init__(self, answering: set[str]) -> None:
        super().__init__()
        self.answering = answering
        self.refreshed_at: list[str | None] = []
        self.last_refresh_error: str | None = None

    def refresh(self, base_url: str | None = None) -> bool:
        self.refreshed_at.append(base_url)
        url = base_url or "http://192.0.2.10:80"
        ok = url in self.answering
        self.last_refresh_error = None if ok else "unreachable: ConnectTimeout"
        return ok


def _paired_store(tmp_path) -> PairingStore:
    store = PairingStore(tmp_path / "pairing.json")
    store.save(_result().pairing)
    return store


def test_a_resumed_pairing_is_reported_as_a_redeem(tmp_path):
    observer = _Observer()
    lifecycle = LinkLifecycle(
        _paired_store(tmp_path), _FakeClient(), discover=lambda timeout_s: None, observer=observer
    )
    _run_until(lifecycle, lambda: lifecycle.state.paired)
    assert observer.events[0][0] == "redeemed"


def test_a_failed_heartbeat_is_reported_as_a_failed_re_redeem(tmp_path, monkeypatch):
    import maipai_body.link.lifecycle as module

    monkeypatch.setattr(module, "REFRESH_INTERVAL_S", 0.02)
    monkeypatch.setattr(module, "DISCOVERY_RETRY_S", 0.02)
    client = _AddressClient(answering=set())
    client.refresh_results = [True]
    observer = _Observer()
    store = _paired_store(tmp_path)

    # first redeem succeeds, every later one fails
    calls = {"n": 0}
    real_refresh = client.refresh

    def refresh(base_url=None):
        calls["n"] += 1
        if calls["n"] == 1:
            client.last_refresh_error = None
            return True
        return real_refresh(base_url)

    client.refresh = refresh
    lifecycle = LinkLifecycle(store, client, discover=lambda timeout_s: None, observer=observer)
    _run_until(lifecycle, lambda: any(e[0] == "failed" for e in observer.events))

    failed = [e for e in observer.events if e[0] == "failed"]
    assert failed and failed[0][1] == "unreachable: ConnectTimeout"


def test_the_walk_redeems_at_the_address_that_answers_and_reports_the_path(tmp_path):
    new_lan = "http://192.0.2.77:80"
    client = _AddressClient(answering={new_lan})
    observer = _Observer()
    lifecycle = LinkLifecycle(
        _paired_store(tmp_path),
        client,
        discover=lambda timeout_s: HubAddress(
            host="192.0.2.77", port=80, instance_id="hub-test", name="Hub", tls=False
        ),
        observer=observer,
        address_walk=True,
    )

    assert lifecycle.reconnect_once() is True

    assert client.refreshed_at == ["http://192.0.2.10:80", new_lan]
    assert ("redeemed", "lan", new_lan) in observer.events
    assert [e for e in observer.events if e[0] == "attempt"] == [
        ("attempt", "http://192.0.2.10:80"),
        ("attempt", new_lan),
    ]
    assert lifecycle.state.paired is True


def test_the_walk_tries_the_tailnet_entry_after_the_lan(tmp_path):
    tailnet = HubEndpoint(PathKind.TAILNET, "http://hub.tail1.ts.net:80", "tailnet")
    client = _AddressClient(answering={tailnet.base_url})
    observer = _Observer()
    lifecycle = LinkLifecycle(
        _paired_store(tmp_path),
        client,
        discover=lambda timeout_s: None,
        observer=observer,
        address_walk=True,
        tailnet=lambda: [tailnet],
    )

    assert lifecycle.reconnect_once() is True

    assert client.refreshed_at == ["http://192.0.2.10:80", tailnet.base_url]
    assert ("redeemed", "tailnet", tailnet.base_url) in observer.events


def test_a_walk_that_finds_nothing_reports_the_last_error_and_returns_false(tmp_path):
    client = _AddressClient(answering=set())
    observer = _Observer()
    lifecycle = LinkLifecycle(
        _paired_store(tmp_path),
        client,
        discover=lambda timeout_s: None,
        observer=observer,
        address_walk=True,
    )

    assert lifecycle.reconnect_once() is False

    assert observer.events[-1] == ("failed", "unreachable: ConnectTimeout")


def test_reconnect_once_with_no_pairing_is_false_and_says_not_paired(tmp_path):
    observer = _Observer()
    lifecycle = LinkLifecycle(
        PairingStore(tmp_path / "none.json"),
        _AddressClient(set()),
        discover=lambda timeout_s: None,
        observer=observer,
        address_walk=True,
    )
    assert lifecycle.reconnect_once() is False
    assert observer.events[-1] == ("failed", "not paired")


def test_a_persisted_pairing_is_retried_while_the_hub_is_away_never_re_paired(
    tmp_path, monkeypatch
):
    """The hub was away at boot: the stored pairing is retried on the
    discovery cadence, so when it answers there is no new code to approve."""
    import maipai_body.link.lifecycle as module

    monkeypatch.setattr(module, "DISCOVERY_RETRY_S", 0.02)
    client = _FakeClient()
    client.refresh_results = [False, False, True]
    lifecycle = LinkLifecycle(_paired_store(tmp_path), client, discover=lambda timeout_s: None)

    _run_until(lifecycle, lambda: lifecycle.state.paired)

    assert lifecycle.state.paired is True
    assert client.request_code_calls == 0
    assert client.refresh_calls == 3


def test_without_the_walk_flag_the_single_address_path_is_unchanged(tmp_path):
    client = _FakeClient()
    lifecycle = LinkLifecycle(_paired_store(tmp_path), client, discover=lambda timeout_s: None)
    stop = threading.Event()
    t = threading.Thread(target=lifecycle.run, args=(stop,), daemon=True)
    t.start()
    for _ in range(100):
        if lifecycle.state.paired:
            break
        threading.Event().wait(0.01)
    stop.set()
    t.join(timeout=2.0)
    assert client.refresh_calls == 1
