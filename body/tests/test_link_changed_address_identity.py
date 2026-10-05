"""LINK-STATE-01 review fix: who may receive the device token at a changed
address, and what an authoritative refusal stops.

Everything here runs the REAL ``HubLinkClient`` against local stand-in hubs
(loopback only; ``example.com`` names are never contacted), not the fake."""

from __future__ import annotations

import http.server
import threading

import pytest

from maipai_body.link.address_walk import AddressWalker, HubEndpoint, PathKind
from maipai_body.link.client import HubLinkClient
from maipai_body.link.discovery import HubAddress
from maipai_body.link.lifecycle import LinkLifecycle
from maipai_body.link.store import HubPairing, PairingStore
from tests.test_link_client import _never_discovers, _StandInHub
from tests.test_link_client_https import https_stand_in_hub  # noqa: F401

PAIRED_NAME = "http://hub.example.com:8080"  # where the pairing was made; never contacted
INSTANCE = "hub-test"


class _Hub:
    """One stand-in hub with its own redeem counter and status."""

    def __init__(self, status: int = 200) -> None:
        self.handler = type("_H", (_StandInHub,), {"redeem_status": status, "redeem_calls": 0})
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    @property
    def calls(self) -> int:
        return self.handler.redeem_calls

    def address(self, instance_id: str = INSTANCE) -> HubAddress:
        return HubAddress(
            host="127.0.0.1",
            port=self.server.server_port,
            instance_id=instance_id,
            name="Hub",
            tls=False,
        )


@pytest.fixture
def hubs():
    made: list[_Hub] = []

    def make(status: int = 200) -> _Hub:
        hub = _Hub(status)
        made.append(hub)
        return hub

    yield make
    for hub in made:
        hub.server.shutdown()


def _store(tmp_path, base_url: str, fingerprint: str | None = INSTANCE) -> PairingStore:
    store = PairingStore(tmp_path / "pairing.json")
    store.save(
        HubPairing(
            base_url=base_url,
            device_token="tok-123",
            hub_instance_id=INSTANCE,
            fingerprint=fingerprint,
        )
    )
    return store


# ---- (a) identity at a changed address, plain http ---------------------------------------------


def test_http_changed_address_with_the_pairings_instance_id_is_verified(hubs, tmp_path):
    hub = hubs()
    client = HubLinkClient(_store(tmp_path, PAIRED_NAME), discover=_never_discovers)

    # Reached at a different host than at pairing time; mDNS (if asked) would
    # advertise the LAN name, which must not matter.
    assert client.refresh(base_url=hub.url, instance_id=INSTANCE) is True
    assert hub.calls == 1


def test_http_changed_address_ignores_what_mdns_advertises_for_the_lan_name(hubs, tmp_path):
    hub = hubs()
    lan_name = HubAddress(host="hub.local", port=8080, instance_id=INSTANCE, name="Hub", tls=False)
    client = HubLinkClient(_store(tmp_path, PAIRED_NAME), discover=lambda timeout_s: lan_name)

    assert client.refresh(base_url=hub.url, instance_id=INSTANCE) is True
    assert hub.calls == 1
    assert client.last_refresh_kind is None


def test_http_changed_address_without_proof_never_gets_the_token(hubs, tmp_path):
    hub = hubs()
    client = HubLinkClient(_store(tmp_path, PAIRED_NAME), discover=_never_discovers)

    assert client.refresh(base_url=hub.url) is False

    assert hub.calls == 0
    assert client.last_refresh_kind == "identity"
    assert client.last_refresh_error.startswith("refused: ")


def test_http_changed_address_with_another_instance_id_never_gets_the_token(hubs, tmp_path):
    hub = hubs()
    client = HubLinkClient(_store(tmp_path, PAIRED_NAME), discover=_never_discovers)

    assert client.refresh(base_url=hub.url, instance_id="someone-elses-hub") is False

    assert hub.calls == 0
    assert client.last_refresh_kind == "identity"


def test_a_walk_never_sends_the_token_to_an_unproven_or_mismatched_endpoint(hubs, tmp_path):
    imposter = hubs()  # mDNS says it is some other hub
    proven = hubs()  # the address book (tailnet seam) carries the pairing's instance id
    store = _store(tmp_path, "http://127.0.0.1:1")  # the paired address: nothing there
    client = HubLinkClient(store, discover=_never_discovers)
    link = LinkLifecycle(
        store,
        client,
        discover=lambda timeout_s: imposter.address("someone-elses-hub"),
        address_walk=True,
        tailnet=lambda: [
            HubEndpoint(PathKind.TAILNET, proven.url, "tailnet", instance_id=INSTANCE)
        ],
    )

    assert link.reconnect_once() is True

    assert imposter.calls == 0  # identity mismatch: token not sent, the walk went on
    assert proven.calls == 1
    assert store.load().base_url == "http://127.0.0.1:1"  # a tailnet answer is never kept


# ---- (a) identity at a changed address, https --------------------------------------------------


def test_https_changed_address_is_verified_by_the_pinned_certificate(https_stand_in_hub, tmp_path):  # noqa: F811
    server, handler, real_fingerprint, cert_path = https_stand_in_hub
    store = _store(tmp_path, "https://hub.example.com:443", fingerprint=real_fingerprint)
    session = _trusting_session(cert_path)
    client = HubLinkClient(store, session=session)

    ok = client.refresh(base_url=f"https://127.0.0.1:{server.server_port}")
    assert ok is True, client.last_refresh_error
    assert handler.redeem_calls == 1


def test_https_changed_address_with_a_different_certificate_never_gets_the_token(
    https_stand_in_hub,  # noqa: F811
    tmp_path,
):
    server, handler, _real, cert_path = https_stand_in_hub
    store = _store(tmp_path, "https://hub.example.com:443", fingerprint="0" * 64)
    client = HubLinkClient(store, session=_trusting_session(cert_path))

    assert client.refresh(base_url=f"https://127.0.0.1:{server.server_port}") is False

    assert handler.redeem_calls == 0
    assert client.last_refresh_kind == "identity"


def test_https_changed_address_with_nothing_pinned_never_gets_the_token(
    https_stand_in_hub,  # noqa: F811
    tmp_path,
):
    server, handler, _real, cert_path = https_stand_in_hub
    store = _store(tmp_path, "https://hub.example.com:443", fingerprint=None)
    client = HubLinkClient(store, session=_trusting_session(cert_path))

    assert client.refresh(base_url=f"https://127.0.0.1:{server.server_port}") is False

    assert handler.redeem_calls == 0
    assert client.last_refresh_kind == "identity"


def _trusting_session(cert_path: str):
    import requests

    session = requests.Session()
    session.verify = cert_path
    return session


# ---- (b) failure kinds in the walk -------------------------------------------------------------


def test_a_network_failure_is_kind_unreachable(tmp_path):
    client = HubLinkClient(_store(tmp_path, "http://127.0.0.1:2"), discover=_never_discovers)
    assert client.refresh(base_url="http://127.0.0.1:1", instance_id=INSTANCE) is False
    assert client.last_refresh_kind == "unreachable"


def test_a_401_from_a_verified_hub_stops_the_walk_and_the_token_goes_nowhere_else(hubs, tmp_path):
    refusing = hubs(status=401)  # the paired address: the hub, and it says revoked
    other = hubs()  # mDNS answer further down the walk, would accept the token
    store = _store(tmp_path, refusing.url)
    client = HubLinkClient(store, discover=_never_discovers)
    events: list[tuple] = []

    class _Observer:
        def attempt(self, address):
            events.append(("attempt", address))

        def redeemed(self, path, address=None):
            events.append(("redeemed", path))

        def redeem_failed(self, error):
            events.append(("failed", error))

    link = LinkLifecycle(
        store,
        client,
        discover=lambda timeout_s: other.address(),
        observer=_Observer(),
        address_walk=True,
    )

    assert link.reconnect_once() is False

    assert refusing.calls == 1
    assert other.calls == 0  # never sent anywhere else
    failed = [e for e in events if e[0] == "failed"]
    assert len(failed) == 1 and "revoked" in failed[0][1]
    assert not any(e == ("attempt", other.url) for e in events)


def test_a_revoked_pairing_is_not_retried(hubs, tmp_path):
    refusing = hubs(status=403)
    store = _store(tmp_path, refusing.url)
    link = LinkLifecycle(
        store,
        HubLinkClient(store, discover=_never_discovers),
        discover=lambda timeout_s: None,
        address_walk=True,
    )

    assert link.reconnect_once() is False
    assert refusing.calls == 1
    for _ in range(5):  # the supervisor's cadence and every wake's retry
        assert link.reconnect_once() is False
    assert refusing.calls == 1  # the dead token is not presented again


def test_a_revoked_pairing_re_pairs_when_a_new_token_is_stored(hubs, tmp_path):
    refusing = hubs(status=401)
    store = _store(tmp_path, refusing.url)
    link = LinkLifecycle(
        store,
        HubLinkClient(store, discover=_never_discovers),
        discover=lambda timeout_s: None,
        address_walk=True,
    )
    assert link.reconnect_once() is False
    refusing.handler.redeem_status = 200
    store.save(
        HubPairing(
            base_url=refusing.url,
            device_token="fresh-token",
            hub_instance_id=INSTANCE,
            fingerprint=INSTANCE,
        )
    )
    assert link.reconnect_once() is True  # a different token is tried


def _walker(outcomes: dict[str, tuple]):
    tried: list[str] = []

    def try_endpoint(endpoint: HubEndpoint):
        tried.append(endpoint.base_url)
        return outcomes.get(endpoint.base_url, (False, "unreachable: x", "unreachable"))

    paired = "http://192.0.2.10:80"
    walker = AddressWalker(
        paired_base_url=lambda: paired,
        discover=lambda timeout_s: HubAddress(
            host="192.0.2.77", port=80, instance_id=INSTANCE, name="Hub", tls=False
        ),
        tailnet=lambda: [HubEndpoint(PathKind.TAILNET, "http://hub.tail1.ts.net:80", "tailnet")],
        try_endpoint=try_endpoint,
    )
    return walker, tried


def test_the_walk_goes_on_after_unreachable_and_after_an_identity_mismatch():
    walker, tried = _walker(
        {
            "http://192.0.2.10:80": (False, "unreachable: x", "unreachable"),
            "http://192.0.2.77:80": (False, "refused: other hub", "identity"),
            "http://hub.tail1.ts.net:80": (True, None, None),
        }
    )
    result = walker.walk()
    assert tried == ["http://192.0.2.10:80", "http://192.0.2.77:80", "http://hub.tail1.ts.net:80"]
    assert result.answered is not None and not result.revoked


def test_the_walk_stops_at_a_revoked_answer():
    walker, tried = _walker({"http://192.0.2.10:80": (False, "refused: 401", "revoked")})
    result = walker.walk()
    assert tried == ["http://192.0.2.10:80"]
    assert result.revoked and result.answered is None


def test_a_revoked_pairing_on_the_run_loop_stops_presenting_the_token_and_asks_for_a_code(
    tmp_path, monkeypatch
):
    import maipai_body.link.lifecycle as module
    from tests.test_link_lifecycle import _result, _run_until
    from tests.test_link_lifecycle_ladder import _AddressClient

    monkeypatch.setattr(module, "DISCOVERY_RETRY_S", 0.01)
    discoveries: list[float] = []

    def discover(timeout_s: float):
        discoveries.append(timeout_s)
        return None  # no hub to pair with yet

    class _Revoked(_AddressClient):
        def refresh(self, base_url=None, persist=True, instance_id=None):
            self.refreshed_at.append(base_url)
            self.last_refresh_error = "refused: hub refused redemption: 401"
            self.last_refresh_kind = "revoked"
            return False

    store = PairingStore(tmp_path / "pairing.json")
    store.save(_result().pairing)
    client = _Revoked(set())
    link = LinkLifecycle(store, client, discover=discover)

    _run_until(link, lambda: len(discoveries) >= 4)

    assert len(client.refreshed_at) == 1  # the dead token went out once
    assert link.state.paired is False
