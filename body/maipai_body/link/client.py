"""G4: the robot's own hub pairing and session client.

Talks to the real, already-shipped hub endpoints (verified directly in
`home`'s own route source, not assumed): `POST /api/auth/quick-connect/
code`, `GET /api/auth/quick-connect/poll`, `POST /api/auth/devices/
redeem`. Identity check before every redeem (`_verify_identity`, called
from `_redeem`, not a side method callers can forget to call): an
https hub is checked against its real TLS certificate's sha256, pinned
at pairing time - a confirmed mismatch refuses the redeem before the
device token is ever sent, and this is the check that provides real
protection. A plain-http LAN hub (this session's own practical dev/sim
path - the audit's own text permits either) has no certificate to
check; a fresh mDNS discovery answering at the same host:port with a
different instance_id is a confirmed mismatch too, but this only
catches an implausible collision, not a realistic on-path spoof (an
attacker who took over the address simply won't advertise mDNS, so
the check finds nothing and proceeds - see `_verify_identity`'s own
docstring for the honest accounting). Plain http has no real defense
against a capable attacker; that is a known, accepted property of
choosing http, not something masked by this check.
"""

from __future__ import annotations

import hashlib
import logging
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from maipai_body.link.discovery import DiscoverHub, HubAddress, discover_hub
from maipai_body.link.store import HubPairing, PairingStore

logger = logging.getLogger("maipai_body.link.client")

POLL_INTERVAL_S = 2.0
POLL_TIMEOUT_S = 300.0  # 5 minutes, matching the code's own server-side TTL


class PairingRefused(RuntimeError):
    """The hub actively refused pairing or redemption (a fingerprint
    mismatch, an unrotated robot credential, an expired/unknown token) -
    distinct from a network failure, which is worth retrying."""


class PairingTimedOut(RuntimeError):
    """No approval arrived within the code's own 5-minute window."""


@dataclass
class PairingResult:
    pairing: HubPairing
    code: str  # shown on the settings page while waiting for approval


@dataclass
class PendingCode:
    base_url: str
    fingerprint: str
    code: str
    poll_token: str
    hub_instance_id: str


def _https_fingerprint(host: str, port: int, timeout_s: float = 5.0) -> str:
    """The peer certificate's sha256, hex-encoded.

    ``ssl.get_server_certificate`` is the stdlib's own purpose-built
    cert-fetch helper (the same primitive `openssl s_client`-style
    inspection tools use) - it fetches the certificate presented on
    the wire without establishing a verified application-data
    connection, which is the point: pinning IS the trust model here,
    not a substitute for one weakened elsewhere in this client. No
    other request in this module ever disables certificate
    verification."""
    pem = ssl.get_server_certificate((host, port), timeout=timeout_s)
    der = ssl.PEM_cert_to_DER_cert(pem)
    return hashlib.sha256(der).hexdigest()


class HubLinkClient:
    """Pairs with a discovered hub, then keeps a session alive across
    restarts by re-redeeming the persisted device token."""

    def __init__(
        self,
        store: PairingStore,
        *,
        session: requests.Session | None = None,
        discover: DiscoverHub = discover_hub,
    ) -> None:
        self._store = store
        self._session = session or requests.Session()
        self._discover = discover

    @property
    def session_cookie(self) -> str | None:
        """The hub's own `session` cookie from the last successful
        redeem, or `None` before one has happened. Other clients that
        talk to the hub over a different transport (`speech/stt_stream.
        py`'s WebSocket, for one - `websockets` doesn't share `requests`'
        own cookie jar) authenticate by sending this value as a `Cookie`
        header, the same credential `requireAuth`'s own middleware reads
        for every other authenticated hub route."""
        return self._session.cookies.get("session")

    def _base_url(self, address: HubAddress) -> str:
        scheme = "https" if address.tls else "http"
        return f"{scheme}://{address.host}:{address.port}"

    def _expected_fingerprint(self, address: HubAddress) -> str:
        if address.tls:
            return _https_fingerprint(address.host, address.port)
        return address.instance_id  # no certificate on plain http; pin identity instead

    def request_code(
        self, address: HubAddress, *, label: str, capabilities: list[str] | None = None
    ) -> PendingCode:
        """Step one: request a code. Returns immediately with the code
        to show while :meth:`await_approval` waits - split from that
        step specifically so a caller (the settings page) can display
        the code before blocking on approval, not after."""
        base_url = self._base_url(address)
        fingerprint = self._expected_fingerprint(address)
        resp = self._session.post(
            f"{base_url}/api/auth/quick-connect/code",
            json={"label": label, "kind": "robot", "capabilities": capabilities or []},
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()
        return PendingCode(
            base_url=base_url,
            fingerprint=fingerprint,
            code=body["code"],
            poll_token=body["poll_token"],
            hub_instance_id=address.instance_id,
        )

    def await_approval(self, pending: PendingCode) -> PairingResult:
        """Step two: block until the code is approved, redeem the
        resulting device token, and persist the pairing. Raises
        :class:`PairingRefused` or :class:`PairingTimedOut`; never
        leaves a half-written pairing file (the store's own atomic
        replace)."""
        device_token = self._poll_until_approved(pending.base_url, pending.poll_token)
        pairing = HubPairing(
            base_url=pending.base_url,
            device_token=device_token,
            hub_instance_id=pending.hub_instance_id,
            fingerprint=pending.fingerprint,
        )
        # Verifies identity here too, deliberately not skipped: an
        # earlier version of this line reasoned that request_code() "just
        # discovered this address moments ago" and skipped the check as
        # redundant - wrong. _poll_until_approved() above can block for
        # up to POLL_TIMEOUT_S (5 minutes) between discovery and this
        # exact call, the one that first sends the device token. A
        # review caught that the "moments ago" premise was false and the
        # skip reopened the very gap _verify_identity() exists to close,
        # for the highest-stakes redeem of all. The mDNS check's own ~3s
        # cost is negligible against a multi-minute pairing flow anyway.
        self._redeem(pairing)  # confirms the token works before saving
        self._store.save(pairing)
        return PairingResult(pairing=pairing, code=pending.code)

    def pair(
        self, address: HubAddress, *, label: str, capabilities: list[str] | None = None
    ) -> PairingResult:
        """Convenience wrapper for a caller that doesn't need to show
        the code before approval completes (mainly tests) - does both
        steps in sequence."""
        pending = self.request_code(address, label=label, capabilities=capabilities)
        return self.await_approval(pending)

    def _poll_until_approved(self, base_url: str, poll_token: str) -> str:
        deadline = time.monotonic() + POLL_TIMEOUT_S
        while time.monotonic() < deadline:
            resp = self._session.get(
                f"{base_url}/api/auth/quick-connect/poll",
                params={"poll_token": poll_token},
                timeout=10,
            )
            resp.raise_for_status()
            body = resp.json()
            if body["status"] == "approved":
                return body["device_token"]
            if body["status"] == "expired":
                raise PairingRefused("the pairing code expired before it was approved")
            time.sleep(POLL_INTERVAL_S)
        raise PairingTimedOut(f"no approval within {POLL_TIMEOUT_S:.0f}s")

    def _redeem(self, pairing: HubPairing) -> None:
        """Exchange the device token for a session cookie on this
        pairing's own base_url. Raises :class:`PairingRefused` on a
        confirmed identity mismatch (see :meth:`_verify_identity`,
        always called first - every redeem path in this class runs it,
        including the first one, right after pairing; an earlier
        version skipped it there on the mistaken premise that little
        time had passed since discovery, when the approval wait alone
        can be up to five minutes), or on 401 (unknown/expired token,
        disabled profile) or 403 (an unrotated robot credential -
        ROBOT-DEVICE-01's own gate)."""
        self._verify_identity(pairing)
        resp = self._session.post(
            f"{pairing.base_url}/api/auth/devices/redeem",
            json={"token": pairing.device_token},
            timeout=10,
        )
        if resp.status_code in (401, 403):
            raise PairingRefused(f"hub refused redemption: {resp.status_code} {resp.text[:200]}")
        resp.raise_for_status()

    def _verify_identity(self, pairing: HubPairing) -> None:
        """Refuses (raises :class:`PairingRefused`) only on a
        *confirmed* identity mismatch - never on an inconclusive check,
        since refusing the robot's own credential on a flaky network is
        worse than a narrow, honestly-scoped defense.

        An https pairing gets a REAL check: the peer certificate
        presented right now must hash to the same value pinned at
        pairing time, so a DHCP-reassigned address or a LAN spoof
        presenting a different certificate is refused before the
        device token is ever sent. This is the case that actually
        matters against a real attacker.

        A plain-http pairing has no certificate to check, so fresh
        mDNS discovery is attempted instead - but be honest about what
        this catches: only the narrow case of a SECOND, differently-
        identified responder answering at the identical host:port
        during the ~3s check window (a real but implausible collision).
        It is NOT a defense against the realistic threat (an attacker
        who has taken over the address - ARP spoof, DHCP reassignment -
        simply doesn't run an mDNS responder at all, so this check
        finds nothing and, correctly per its own inconclusive-is-not-
        a-mismatch rule, proceeds anyway). Plain-http pairing has no
        real protection against a capable on-path attacker; https is
        the only path with one. This is a known, accepted limitation
        of choosing http for a LAN/dev/sim deployment (the audit's own
        text permits either), not something this check silently
        pretends to solve."""
        if pairing.fingerprint is None:
            return
        parsed = urlparse(pairing.base_url)
        host, port = parsed.hostname, parsed.port
        if host is None or port is None:
            return
        if parsed.scheme == "https":
            try:
                actual = _https_fingerprint(host, port)
            except (OSError, ssl.SSLError) as exc:
                logger.warning("could not verify hub certificate before redeeming: %s", exc)
                return  # inconclusive (host unreachable for the check) - not a mismatch
            if actual != pairing.fingerprint:
                raise PairingRefused(
                    f"hub at {pairing.base_url} presented a different TLS certificate "
                    "than the one this pairing was made with"
                )
            return
        address = self._discover(timeout_s=3.0)
        if address is None or address.host != host or address.port != port:
            return  # inconclusive: no fresh answer for this host, or a different service
        if address.instance_id != pairing.fingerprint:
            raise PairingRefused(
                f"hub at {pairing.base_url} now advertises a different instance id "
                "than the one this pairing was made with"
            )

    def refresh(self) -> bool:
        """Re-establish a session from the persisted pairing, e.g. at
        startup or after a 401 mid-session. Returns False (never
        raises) when there is no pairing, or the hub refuses it - the
        caller's own offline-first floor handles either the same way."""
        pairing = self._store.load()
        if pairing is None:
            return False
        try:
            self._redeem(pairing)
        except (PairingRefused, requests.RequestException):
            return False
        return True
