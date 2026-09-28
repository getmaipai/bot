"""G4: the link's own small state machine - unpaired, pairing, paired.

A free-standing, injectable class (the same shape ``app.run_body`` set:
"a free function/class, not a method, so the deterministic suite drives
it directly with fakes"), so the settings page's ``/api/state`` route
and the daemon's own real ``__main__`` wiring both just read
``LinkLifecycle.state`` rather than duplicating this logic.
"""

from __future__ import annotations

import copy
import logging
import threading
from dataclasses import dataclass

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
    ) -> None:
        self._store = store
        self._client = client
        self._discover = discover
        self._label = label
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
            if stop_event.is_set():
                return
            self._heartbeat(stop_event)

    def _try_existing_pairing(self) -> bool:
        pairing = self._store.load()
        if pairing is None:
            return False
        if self._client.refresh():
            self._set_state(
                paired=True, code=None, hub_instance_id=pairing.hub_instance_id, last_error=None
            )
            logger.info("resumed hub session from a persisted pairing")
            return True
        logger.warning("persisted pairing could not be refreshed; will re-pair")
        return False

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
            if not self._client.refresh():
                logger.warning("session refresh failed; re-pairing")
                self._set_state(paired=False)
                return
