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
        self.address_book: list[dict] = []
        self.fetch_calls = 0

    def fetch_hub_endpoints(self, base_url=None):
        self.fetch_calls += 1
        return self.address_book

    def refresh(
        self, base_url: str | None = None, persist: bool = True, instance_id: str | None = None
    ) -> bool:
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


def test_lifecycle_refreshes_address_book_then_uses_overlay_only_for_joined_host(
    tmp_path, monkeypatch
):
    joined = [True]
    client = _AddressClient(answering={"http://192.0.2.10:80"})
    client.address_book = [
        {
            "url": "http://hub.tail1234.ts.net:80",
            "kind": "overlay",
            "enabled": True,
            "priority": 60,
            "instanceId": "hub-test",
        }
    ]
    lifecycle = LinkLifecycle(
        _paired_store(tmp_path),
        client,
        discover=lambda timeout_s: HubAddress("192.0.2.77", 80, "hub-test", "Hub", False),
        address_walk=True,
        tailnet_member=lambda: joined[0],
    )

    assert lifecycle.reconnect_once()  # LAN reachable, refreshes address book
    assert client.fetch_calls == 1
    client.answering = {"http://hub.tail1234.ts.net:80"}
    assert lifecycle.reconnect_once()
    assert client.refreshed_at[-1] == "http://hub.tail1234.ts.net:80"
    assert client.fetch_calls == 2
    joined[0] = False
    client.answering = set()
    before = len(client.refreshed_at)
    assert not lifecycle.reconnect_once()
    assert "http://hub.tail1234.ts.net:80" not in client.refreshed_at[before:]


def test_key_off_book_and_nonmember_skip_overlay(tmp_path, monkeypatch):
    joined = [True]
    client = _AddressClient(answering=set())
    client.address_book = []  # The hub's key-off response contains LAN rows only.
    lifecycle = LinkLifecycle(
        _paired_store(tmp_path),
        client,
        discover=lambda timeout_s: None,
        address_walk=True,
        tailnet_member=lambda: joined[0],
    )
    assert not lifecycle.reconnect_once()
    assert client.refreshed_at == ["http://192.0.2.10:80"]

    joined[0] = False
    client.address_book = [
        {
            "url": "http://hub.tail1234.ts.net:80",
            "kind": "overlay",
            "enabled": True,
            "priority": 60,
            "instanceId": "hub-test",
        }
    ]
    assert lifecycle.reconnect_once() is False
    assert client.refreshed_at[-1] == "http://192.0.2.10:80"


def test_address_book_lan_rows_follow_server_priority_and_total_failure_reports_to_ladder(
    tmp_path,
):
    observer = _Observer()
    client = _AddressClient(answering=set())
    client.address_book = [
        {
            "url": "http://192.0.2.20:80",
            "kind": "lan",
            "enabled": True,
            "priority": 20,
            "instanceId": "hub-test",
        },
        {
            "url": "http://192.0.2.19:80",
            "kind": "lan",
            "enabled": True,
            "priority": 10,
            "instanceId": "hub-test",
        },
    ]
    lifecycle = LinkLifecycle(
        _paired_store(tmp_path),
        client,
        discover=lambda timeout_s: None,
        address_walk=True,
        observer=observer,
        tailnet_member=lambda: True,
    )
    lifecycle._refresh_address_book()

    assert [endpoint.base_url for endpoint in lifecycle._lan_candidates()] == [
        "http://192.0.2.19:80",
        "http://192.0.2.20:80",
    ]
    assert lifecycle.reconnect_once() is False
    assert observer.events[-1][0] == "failed"


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

    def refresh(base_url=None, persist=True, instance_id=None):
        calls["n"] += 1
        if calls["n"] == 1:
            client.last_refresh_error = None
            return True
        return real_refresh(base_url, persist, instance_id)

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
