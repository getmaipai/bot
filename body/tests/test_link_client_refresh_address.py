"""LINK-STATE-01: a redeem at a chosen address, the one the walk found."""

from __future__ import annotations

from maipai_body.link.client import HubLinkClient
from maipai_body.link.store import HubPairing, PairingStore
from tests.test_link_client import _never_discovers, stand_in_hub  # noqa: F401


def _store(tmp_path, base_url: str) -> PairingStore:
    store = PairingStore(tmp_path / "pairing.json")
    store.save(
        HubPairing(
            base_url=base_url,
            device_token="tok-123",
            hub_instance_id="hub-test",
            fingerprint="hub-test",
        )
    )
    return store


def test_refresh_at_another_address_redeems_there_and_keeps_it(stand_in_hub, tmp_path):  # noqa: F811
    server, handler = stand_in_hub
    store = _store(tmp_path, "http://127.0.0.1:1")  # the old address, nothing there
    client = HubLinkClient(store, discover=_never_discovers)
    new_url = f"http://127.0.0.1:{server.server_port}"

    assert client.refresh(base_url=new_url) is True

    assert handler.redeem_calls == 1
    assert store.load().base_url == new_url
    assert store.load().device_token == "tok-123"
    assert client.last_refresh_error is None


def test_a_failed_redeem_at_another_address_leaves_the_pairing_alone(tmp_path):
    store = _store(tmp_path, "http://127.0.0.1:2")
    client = HubLinkClient(store, discover=_never_discovers)

    assert client.refresh(base_url="http://127.0.0.1:1") is False

    assert store.load().base_url == "http://127.0.0.1:2"
    assert client.last_refresh_error.startswith("unreachable: ")


def test_a_refusal_is_reported_as_refused_not_unreachable(stand_in_hub, tmp_path):  # noqa: F811
    server, handler = stand_in_hub
    handler.redeem_status = 401
    store = _store(tmp_path, f"http://127.0.0.1:{server.server_port}")
    client = HubLinkClient(store, discover=_never_discovers)

    assert client.refresh() is False

    assert client.last_refresh_error.startswith("refused: ")


def test_no_pairing_is_its_own_error(tmp_path):
    client = HubLinkClient(PairingStore(tmp_path / "none.json"), discover=_never_discovers)
    assert client.refresh() is False
    assert client.last_refresh_error == "not paired"
