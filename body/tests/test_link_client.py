"""G4's own acceptance: pair, redeem, refresh, refuse - against a real
local HTTP server standing in for the hub (RM-03's own pattern), so the
whole HTTP path (headers, JSON, status codes) is exercised for real,
not mocked at the requests layer."""

from __future__ import annotations

import http.server
import json
import threading

import pytest

from maipai_body.link.client import (
    HubLinkClient,
    PairingRefused,
)
from maipai_body.link.discovery import HubAddress
from maipai_body.link.store import PairingStore


class _StandInHub(http.server.BaseHTTPRequestHandler):
    """A scripted stand-in for the three real hub endpoints G4 calls.
    Each test configures the class-level script before starting the
    server; ``poll_responses`` is popped one at a time per /poll call,
    the last entry repeating once exhausted."""

    label_seen: str | None = None
    kind_seen: str | None = None
    capabilities_seen: list | None = None
    poll_responses: list[dict] = [
        {"status": "approved", "device_token": "tok-123", "expires_at": "2027-01-01"}
    ]
    redeem_status: int = 200
    redeem_calls: int = 0

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # silence the default stderr access log

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/auth/quick-connect/code":
            type(self).label_seen = body.get("label")
            type(self).kind_seen = body.get("kind")
            type(self).capabilities_seen = body.get("capabilities")
            self._send_json(200, {"code": "AB12CD", "poll_token": "poll-xyz"})
        elif self.path == "/api/auth/devices/redeem":
            type(self).redeem_calls += 1
            if self.redeem_status != 200:
                self._send_json(self.redeem_status, {"error": "refused"})
            else:
                self._send_json(200, {"success": True})
        else:
            self._send_json(404, {"error": "not found"})

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        if self.path.startswith("/api/auth/quick-connect/poll"):
            responses = type(self).poll_responses
            next_response = responses.pop(0) if len(responses) > 1 else responses[0]
            self._send_json(200, next_response)
        else:
            self._send_json(404, {"error": "not found"})


@pytest.fixture
def stand_in_hub():
    _StandInHub.label_seen = None
    _StandInHub.capabilities_seen = None
    _StandInHub.poll_responses = [
        {"status": "approved", "device_token": "tok-123", "expires_at": "2027-01-01"}
    ]
    _StandInHub.redeem_status = 200
    _StandInHub.redeem_calls = 0

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StandInHub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, _StandInHub
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _address(server) -> HubAddress:
    return HubAddress(
        host="127.0.0.1",
        port=server.server_port,
        instance_id="hub-test",
        name="Test Hub",
        tls=False,
    )


def _never_discovers(timeout_s: float) -> HubAddress | None:
    """The default stub for every test in this file: a plain-http
    pairing's own identity check treats "no fresh mDNS answer" as
    inconclusive, not a mismatch (see client.py's own
    `_verify_identity` docstring), so tests that don't care about that
    check can just never answer."""
    return None


def _client(store: PairingStore, *, discover=_never_discovers) -> HubLinkClient:
    return HubLinkClient(store, discover=discover)


def test_pair_runs_code_approve_poll_redeem_end_to_end(stand_in_hub, tmp_path):
    server, handler = stand_in_hub
    store = PairingStore(tmp_path / "pairing.json")
    client = _client(store)

    result = client.pair(_address(server), label="Living Room Reachy")

    assert result.code == "AB12CD"
    assert result.pairing.device_token == "tok-123"
    assert result.pairing.hub_instance_id == "hub-test"
    assert handler.label_seen == "Living Room Reachy"
    assert handler.redeem_calls == 1
    # Persisted, not just returned:
    assert store.load() == result.pairing


def test_pair_sends_kind_robot(stand_in_hub, tmp_path):
    """A real hub only ever mints a device_token (not a live session)
    for kind: 'robot' (quickConnect.ts's own poll handler) - confirmed
    the client actually sends that, not a default like 'tv'."""
    server, handler = stand_in_hub
    store = PairingStore(tmp_path / "pairing.json")
    client = _client(store)

    client.pair(_address(server), label="Reachy")

    assert handler.kind_seen == "robot"


def test_poll_waits_through_pending_before_approval(stand_in_hub, tmp_path, monkeypatch):
    server, handler = stand_in_hub
    handler.poll_responses = [
        {"status": "pending"},
        {"status": "pending"},
        {"status": "approved", "device_token": "tok-123", "expires_at": "2027-01-01"},
    ]
    monkeypatch.setattr("maipai_body.link.client.POLL_INTERVAL_S", 0.01)
    store = PairingStore(tmp_path / "pairing.json")
    client = _client(store)

    result = client.pair(_address(server), label="Reachy")

    assert result.pairing.device_token == "tok-123"


def test_an_expired_code_raises_pairing_refused(stand_in_hub, tmp_path):
    server, handler = stand_in_hub
    handler.poll_responses = [{"status": "expired"}]
    store = PairingStore(tmp_path / "pairing.json")
    client = _client(store)

    with pytest.raises(PairingRefused):
        client.pair(_address(server), label="Reachy")

    assert store.load() is None  # never persisted a failed pairing


def test_redeem_401_raises_pairing_refused(stand_in_hub, tmp_path):
    server, handler = stand_in_hub
    handler.redeem_status = 401
    store = PairingStore(tmp_path / "pairing.json")
    client = _client(store)

    with pytest.raises(PairingRefused):
        client.pair(_address(server), label="Reachy")

    assert store.load() is None


def test_redeem_403_unrotated_robot_credential_raises_pairing_refused(stand_in_hub, tmp_path):
    """ROBOT-DEVICE-01's own gate: a robot device token is refused until
    the unit's SSH password is rotated off the vendor default."""
    server, handler = stand_in_hub
    handler.redeem_status = 403
    store = PairingStore(tmp_path / "pairing.json")
    client = _client(store)

    with pytest.raises(PairingRefused):
        client.pair(_address(server), label="Reachy")


def test_refresh_redeems_a_persisted_pairing(stand_in_hub, tmp_path):
    from maipai_body.link.store import HubPairing

    server, handler = stand_in_hub
    store = PairingStore(tmp_path / "pairing.json")
    store.save(
        HubPairing(
            base_url=f"http://127.0.0.1:{server.server_port}",
            device_token="tok-123",
            hub_instance_id="hub-test",
            fingerprint="hub-test",
        )
    )
    client = _client(store)

    assert client.refresh() is True
    assert handler.redeem_calls == 1


def test_refresh_with_no_pairing_returns_false(tmp_path):
    store = PairingStore(tmp_path / "pairing.json")
    client = _client(store)

    assert client.refresh() is False


def test_refresh_returns_false_on_refusal_not_a_raise(stand_in_hub, tmp_path):
    from maipai_body.link.store import HubPairing

    server, handler = stand_in_hub
    handler.redeem_status = 401
    store = PairingStore(tmp_path / "pairing.json")
    store.save(
        HubPairing(
            base_url=f"http://127.0.0.1:{server.server_port}",
            device_token="stale-token",
            hub_instance_id="hub-test",
            fingerprint="hub-test",
        )
    )
    client = _client(store)

    assert client.refresh() is False


def test_refresh_returns_false_when_the_hub_is_unreachable(tmp_path):
    from maipai_body.link.store import HubPairing

    store = PairingStore(tmp_path / "pairing.json")
    store.save(
        HubPairing(
            base_url="http://127.0.0.1:1",  # a port nothing listens on
            device_token="tok-123",
            hub_instance_id="hub-test",
            fingerprint="hub-test",
        )
    )
    client = _client(store)

    assert client.refresh() is False


def test_refresh_refuses_a_confirmed_identity_mismatch(stand_in_hub, tmp_path):
    """The actual fix for the review's own critical finding: a fresh
    discovery answering at the pairing's own host:port with a
    DIFFERENT instance_id is a confirmed mismatch, refused before the
    device token is ever sent."""
    from maipai_body.link.store import HubPairing

    server, handler = stand_in_hub
    store = PairingStore(tmp_path / "pairing.json")
    store.save(
        HubPairing(
            base_url=f"http://127.0.0.1:{server.server_port}",
            device_token="tok-123",
            hub_instance_id="hub-test",
            fingerprint="hub-test",  # what pairing time pinned
        )
    )

    def _spoofed_discover(timeout_s: float) -> HubAddress:
        return HubAddress(
            host="127.0.0.1",
            port=server.server_port,
            instance_id="a-different-hub",  # someone else answering now
            name="Impostor",
            tls=False,
        )

    client = _client(store, discover=_spoofed_discover)

    assert client.refresh() is False
    assert handler.redeem_calls == 0  # refused before the token was ever sent


def test_refresh_proceeds_when_discovery_is_inconclusive(stand_in_hub, tmp_path):
    """A real hub's mDNS just not answering within the check's own
    window is not treated as a mismatch - refusing service on an
    ordinary network hiccup would be worse than the narrow risk this
    check accepts."""
    from maipai_body.link.store import HubPairing

    server, handler = stand_in_hub
    store = PairingStore(tmp_path / "pairing.json")
    store.save(
        HubPairing(
            base_url=f"http://127.0.0.1:{server.server_port}",
            device_token="tok-123",
            hub_instance_id="hub-test",
            fingerprint="hub-test",
        )
    )
    client = _client(store, discover=_never_discovers)

    assert client.refresh() is True
    assert handler.redeem_calls == 1


def test_refresh_proceeds_when_discovery_finds_a_different_service(stand_in_hub, tmp_path):
    """A fresh discovery answering at a DIFFERENT host or port is not
    evidence about the pairing's own hub - only a match on host and
    port with a different instance_id is a confirmed mismatch."""
    from maipai_body.link.store import HubPairing

    server, handler = stand_in_hub
    store = PairingStore(tmp_path / "pairing.json")
    store.save(
        HubPairing(
            base_url=f"http://127.0.0.1:{server.server_port}",
            device_token="tok-123",
            hub_instance_id="hub-test",
            fingerprint="hub-test",
        )
    )

    def _unrelated_discover(timeout_s: float) -> HubAddress:
        return HubAddress(
            host="127.0.0.1",
            port=server.server_port + 1,
            instance_id="some-other-hub",
            name="Elsewhere",
            tls=False,
        )

    client = _client(store, discover=_unrelated_discover)

    assert client.refresh() is True
    assert handler.redeem_calls == 1
