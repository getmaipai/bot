"""G4's own acceptance, the https half: a real self-signed certificate,
a real TLS handshake, a real fingerprint computed from it - the
security-critical path `_verify_identity`'s own docstring says matters
most, and the one a prior review found untested. The cert is generated
by the system's own `openssl` CLI (no new runtime dependency; test-only,
one-shot, thrown away with `tmp_path`), and `requests`' own `verify=`
option trusts that specific cert - never `verify=False`, which would
be the same TLS-weakening pattern `client.py`'s own `_https_fingerprint`
docstring is explicit about never doing."""

from __future__ import annotations

import http.server
import shutil
import ssl
import subprocess
import threading

import pytest
import requests

from maipai_body.link.client import HubLinkClient, _https_fingerprint
from maipai_body.link.discovery import HubAddress
from maipai_body.link.store import HubPairing, PairingStore
from tests.test_link_client import _StandInHub

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI not found")


def _generate_self_signed_cert(tmp_path) -> tuple[str, str]:
    key_path = str(tmp_path / "key.pem")
    cert_path = str(tmp_path / "cert.pem")
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            key_path,
            "-out",
            cert_path,
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            # A CN alone doesn't satisfy modern hostname verification (it
            # needs a matching Subject Alternative Name) - real requests
            # against this server would otherwise fail with a cert error
            # unrelated to anything this test is actually checking.
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    return cert_path, key_path


@pytest.fixture
def https_stand_in_hub(tmp_path):
    _StandInHub.label_seen = None
    _StandInHub.kind_seen = None
    _StandInHub.capabilities_seen = None
    _StandInHub.poll_responses = [
        {"status": "approved", "device_token": "tok-123", "expires_at": "2027-01-01"}
    ]
    _StandInHub.redeem_status = 200
    _StandInHub.redeem_calls = 0

    cert_path, key_path = _generate_self_signed_cert(tmp_path)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StandInHub)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        real_fingerprint = _https_fingerprint("127.0.0.1", server.server_port)
        yield server, _StandInHub, real_fingerprint, cert_path
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _trusting_session(cert_path: str) -> requests.Session:
    """Trusts this one specific self-signed cert, nothing else - never
    `verify=False`, which would disable certificate checking globally."""
    session = requests.Session()
    session.verify = cert_path
    return session


def _address(server) -> HubAddress:
    return HubAddress(
        host="127.0.0.1", port=server.server_port, instance_id="hub-test", name="Test Hub", tls=True
    )


def test_https_pairing_pins_the_real_certificate_fingerprint(https_stand_in_hub, tmp_path):
    server, handler, real_fingerprint, cert_path = https_stand_in_hub
    store = PairingStore(tmp_path / "pairing.json")
    client = HubLinkClient(store, session=_trusting_session(cert_path))

    result = client.pair(_address(server), label="Reachy")

    assert result.pairing.fingerprint == real_fingerprint
    assert result.pairing.base_url.startswith("https://")


def test_https_refresh_succeeds_when_the_certificate_matches(https_stand_in_hub, tmp_path):
    server, handler, real_fingerprint, cert_path = https_stand_in_hub
    store = PairingStore(tmp_path / "pairing.json")
    store.save(
        HubPairing(
            base_url=f"https://127.0.0.1:{server.server_port}",
            device_token="tok-123",
            hub_instance_id="hub-test",
            fingerprint=real_fingerprint,
        )
    )
    client = HubLinkClient(store, session=_trusting_session(cert_path))

    assert client.refresh() is True
    assert handler.redeem_calls == 1


def test_https_refresh_refuses_a_confirmed_certificate_mismatch(https_stand_in_hub, tmp_path):
    """The security-critical case: a pairing pinned to a DIFFERENT
    certificate than the one this hub now presents is refused before
    the device token is ever sent - not silently trusted."""
    server, handler, real_fingerprint, cert_path = https_stand_in_hub
    store = PairingStore(tmp_path / "pairing.json")
    store.save(
        HubPairing(
            base_url=f"https://127.0.0.1:{server.server_port}",
            device_token="tok-123",
            hub_instance_id="hub-test",
            fingerprint="0" * 64,  # not the real certificate's hash
        )
    )
    client = HubLinkClient(store, session=_trusting_session(cert_path))

    assert client.refresh() is False
    assert handler.redeem_calls == 0
