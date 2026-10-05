"""G4: the link's own small state machine - unpaired, pairing, paired.

A free-standing, injectable class (the same shape ``app.run_paired_body``
sets: "a free function/class, not a method, so the deterministic suite
drives it directly with fakes"), so the settings page's ``/api/state`` route
and the daemon's own real ``__main__`` wiring both just read
``LinkLifecycle.state`` rather than duplicating this logic.
"""

from __future__ import annotations

import copy
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from maipai_body.link.address_walk import (
    AddressWalker,
    HubEndpoint,
    PathKind,
    TailnetEndpoints,
    no_tailnet_endpoints,
)
from maipai_body.link.client import HubLinkClient, PairingRefused, PairingTimedOut
from maipai_body.link.discovery import DiscoverHub
from maipai_body.link.store import PairingStore

logger = logging.getLogger("maipai_body.link.lifecycle")

# Re-redeem well inside the hub's own 7-day session lifetime (CLAUDE.md's
# own citation of lib/session.ts) so a missed tick or two is never a risk.
REFRESH_INTERVAL_S = 24.0 * 60 * 60  # 24h
DISCOVERY_RETRY_S = 30.0


@dataclass
class LinkState:
    paired: bool
    code: str | None = None
    hub_instance_id: str | None = None
    last_error: str | None = None


class LinkObserver(Protocol):
    """What the offline ladder's state machine hears from the lifecycle:
    every address tried, every redeem that worked and every one that
    did not (with the client's own reason)."""

    def attempt(self, address: str) -> None: ...

    def redeemed(self, path: str, address: str | None = None) -> None: ...

    def redeem_failed(self, error: str) -> None: ...


class LinkLifecycle:
    """Owns the robot's own view of its hub link across the app's
    lifetime: unpaired (discovering, or showing a code and waiting for
    approval) through paired (periodically re-redeeming so the session
    never lapses)."""

    def __init__(
        self,
        store: PairingStore,
        client: HubLinkClient,
        *,
        discover: DiscoverHub,
        label: str = "Reachy Mini",
        on_code: Callable[[str], None] | None = None,
        observer: LinkObserver | None = None,
        address_walk: bool = False,
        tailnet: TailnetEndpoints = no_tailnet_endpoints,
    ) -> None:
        self._store = store
        self._client = client
        self._discover = discover
        self._label = label
        self._on_code = on_code
        self._observer = observer
        # LINK-STATE-01: with `address_walk` a re-redeem walks the LAN then
        # the tailnet (`tailnet` is ROBOT-TAILSCALE-01's seam) instead of
        # retrying the one stored address.
        self._walker = (
            AddressWalker(
                paired_base_url=self._stored_base_url,
                discover=discover,
                try_endpoint=self._try_endpoint,
                tailnet=tailnet,
                on_attempt=self._note_attempt,
            )
            if address_walk
            else None
        )
        self._redeem_lock = threading.Lock()  # one redeem or walk at a time
        self._lock = threading.Lock()
        self._state = LinkState(paired=False)

    @property
    def state(self) -> LinkState:
        """A snapshot, not the live object: a reader doing several
        attribute accesses (the settings page's own `paired`, `code`,
        `hub_instance_id`) must never see a torn combination from a
        `_set_state()` call landing mid-read - `_set_state`'s own
        multi-field update isn't atomic as a group even though each
        individual `setattr` is lock-protected, so the copy has to
        happen inside the same lock the writer uses."""
        with self._lock:
            return copy.copy(self._state)

    @property
    def pairing_store(self) -> PairingStore:
        """The persisted pairing this lifecycle reads/writes. A caller
        that has just observed `state.paired` and needs the connection
        details (`app.py`'s `run_paired_body`, once it hands off to a
        real hub client) reads this rather than duplicating its own
        copy of the same store - one owner, read from two places."""
        return self._store

    @property
    def hub_client(self) -> HubLinkClient:
        """The `HubLinkClient` this lifecycle drives. Its
        `session_cookie` is live (reads straight off the client's own
        session, `HubLinkClient.session_cookie`'s own docstring), so a
        reader here always sees the cookie from the most recent
        pair/refresh, not a stale copy taken once at construction."""
        return self._client

    def _stored_base_url(self) -> str | None:
        pairing = self._store.load()
        return pairing.base_url if pairing is not None else None

    def _try_endpoint(self, endpoint: HubEndpoint) -> tuple[bool, str | None]:
        # Only a LAN answer becomes the pairing's stored address; a tailnet
        # answer is used for this session and the LAN address stays the record.
        ok = self._client.refresh(base_url=endpoint.base_url, persist=endpoint.kind is PathKind.LAN)
        return ok, None if ok else self._client.last_refresh_error

    def _note_attempt(self, endpoint: HubEndpoint) -> None:
        if self._observer is not None:
            self._observer.attempt(endpoint.base_url)

    def _redeem_existing(self) -> bool:
        """Re-redeem the persisted pairing (walking the address book when
        asked to) and tell the observer what happened. Serialized: the
        heartbeat, the pairing loop and the supervisor all come through here."""
        with self._redeem_lock:
            if self._walker is None:
                ok = self._client.refresh()
                if ok:
                    path, address = "lan", self._stored_base_url()
                    error = None
                else:
                    path, address = "", None
                    error = getattr(self._client, "last_refresh_error", None)
                    error = error or "the hub did not answer"
            else:
                result = self._walker.walk()
                ok = result.answered is not None
                if ok:
                    path, address = result.answered.kind.value, result.answered.base_url
                    error = None
                else:
                    path, address = "", None
                    errors = [a.error for a in result.attempts if a.error]
                    error = errors[-1] if errors else "not paired"
        if self._observer is not None:
            if ok:
                self._observer.redeemed(path, address)
            else:
                self._observer.redeem_failed(error)
        return ok

    def reconnect_once(self) -> bool:
        """One re-redeem of the stored pairing: what the ladder's
        supervisor calls on its own cadence while the link is down. Never
        asks for a new code. True means the hub answered."""
        pairing = self._store.load()
        if pairing is None:
            if self._observer is not None:
                self._observer.redeem_failed("not paired")
            return False
        if self._redeem_existing():
            self._set_state(
                paired=True, code=None, hub_instance_id=pairing.hub_instance_id, last_error=None
            )
            return True
        return False

    def _set_state(self, **changes) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(self._state, key, value)

    def run(self, stop_event: threading.Event) -> None:
        """Blocks until ``stop_event`` is set - run this on its own
        thread. One outer loop, constant stack depth for the life of
        the process: get paired (resume, or discover-and-retry), then
        heartbeat until a refresh fails, then loop back to get paired
        again - never recursion, so a robot that re-pairs many times
        over months never grows its call stack."""
        while not stop_event.is_set():
            paired = self._try_existing_pairing()
            while not paired and not stop_event.is_set():
                paired = self._discover_and_pair()
                if not paired:
                    stop_event.wait(DISCOVERY_RETRY_S)
                    # A stored pairing is retried before asking for a new
                    # code: a hub that was only away answers it with no
                    # approval needed (LINK-STATE-01).
                    paired = self._try_existing_pairing()
            if stop_event.is_set():
                return
            self._heartbeat(stop_event)

    def _try_existing_pairing(self) -> bool:
        pairing = self._store.load()
        if pairing is None:
            return False
        if self._redeem_existing():
            self._set_state(
                paired=True, code=None, hub_instance_id=pairing.hub_instance_id, last_error=None
            )
            logger.info("resumed hub session from a persisted pairing")
            return True
        logger.warning("persisted pairing could not be refreshed; will re-pair")
        return False

    def _announce_code(self, code: str) -> None:
        """G4b: hands the fresh code to the caller's hook (the robot speaks
        it from its offline clips). A failing hook never breaks pairing:
        the code is still on the app page."""
        if self._on_code is None:
            return
        try:
            self._on_code(code)
        except Exception:
            logger.warning("on_code hook failed", exc_info=True)

    def _discover_and_pair(self) -> bool:
        address = self._discover(timeout_s=5.0)
        if address is None:
            self._set_state(last_error="no hub found on the network")
            return False
        try:
            pending = self._client.request_code(address, label=self._label)
            # Surfaced before the blocking wait, not after - this is the
            # whole reason request_code()/await_approval() are split.
            self._set_state(paired=False, code=pending.code, last_error=None)
            self._announce_code(pending.code)
            result = self._client.await_approval(pending)
        except (PairingRefused, PairingTimedOut) as exc:
            self._set_state(code=None, last_error=str(exc))
            logger.warning("pairing failed: %s", exc)
            return False
        self._set_state(
            paired=True, code=None, hub_instance_id=result.pairing.hub_instance_id, last_error=None
        )
        logger.info("paired with hub %s", result.pairing.hub_instance_id)
        return True

    def _heartbeat(self, stop_event: threading.Event) -> None:
        """Re-redeems on a slow interval until a refresh fails or
        ``stop_event`` is set, then returns - never recurses into
        :meth:`run`; the caller's own outer loop is what re-pairs."""
        while not stop_event.wait(REFRESH_INTERVAL_S):
            if not self._redeem_existing():
                logger.warning("session refresh failed; re-pairing")
                self._set_state(paired=False)
                return
