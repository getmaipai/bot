"""LINK-STATE-01: walk the hub's addresses, the LAN first and the tailnet next.

What the code supports today: the address the pairing was made with, a
fresh mDNS answer (``discovery.discover_hub``), and a tailnet provider
that is an empty seam. ROBOT-TAILSCALE-01 (the hub's address-book route
and the bot half that caches it) fills that seam; until then the walk is
LAN only and says so by having nothing to try after the LAN entries.

The walk is lazy: mDNS is asked only if the paired address did not answer.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlparse

from maipai_body.link.discovery import DiscoverHub

logger = logging.getLogger("maipai_body.link.address_walk")

_TAILNET_NET = ipaddress.ip_network("100.64.0.0/10")
DISCOVER_TIMEOUT_S = 3.0


class PathKind(StrEnum):
    LAN = "lan"
    TAILNET = "tailnet"


class FailureKind(StrEnum):
    """Why an endpoint did not take the redeem; the walk acts on it."""

    UNREACHABLE = "unreachable"  # a network failure: try the next address
    IDENTITY = "identity"  # not proven to be the hub, token not sent: next address
    REVOKED = "revoked"  # a 401/403: the hub refused the token, stop the walk


@dataclass(frozen=True)
class HubEndpoint:
    kind: PathKind
    base_url: str
    source: str  # "paired", "mdns" or "tailnet"
    # The hub instance id this address is known to belong to: from the mDNS
    # answer, or from the tailnet address book (ROBOT-TAILSCALE-01 must fill
    # it from the hub's own authenticated response). It is the proof for a
    # plain-http address other than the pairing's own; None means unproven.
    instance_id: str | None = None


def classify_base_url(base_url: str) -> PathKind:
    """A ``.ts.net`` name or a 100.64.0.0/10 address is the tailnet; anything
    else is the LAN (the same split the hub's address book makes)."""
    host = urlparse(base_url).hostname or ""
    if host.endswith(".ts.net"):
        return PathKind.TAILNET
    try:
        if ipaddress.ip_address(host) in _TAILNET_NET:
            return PathKind.TAILNET
    except ValueError:
        pass
    return PathKind.LAN


class TailnetEndpoints(Protocol):
    def __call__(self) -> list[HubEndpoint]: ...


def no_tailnet_endpoints() -> list[HubEndpoint]:
    """SEAM (ROBOT-TAILSCALE-01): the cached tailnet entries of the hub's
    address book, in the server's priority order. Empty until that item's
    bot half lands: no route to fetch the book exists on the hub yet."""
    return []


@dataclass(frozen=True)
class AttemptRecord:
    endpoint: HubEndpoint
    ok: bool
    error: str | None
    failure: FailureKind | None = None


@dataclass
class WalkResult:
    answered: HubEndpoint | None
    attempts: list[AttemptRecord] = field(default_factory=list)
    revoked: bool = False  # an endpoint refused the token; the walk stopped there


# ``(ok, error)`` or ``(ok, error, failure_kind)``; a failure with no kind is
# a network failure.
TryEndpoint = Callable[[HubEndpoint], tuple]


class AddressWalker:
    def __init__(
        self,
        *,
        paired_base_url: Callable[[], str | None],
        discover: DiscoverHub,
        try_endpoint: TryEndpoint,
        tailnet: TailnetEndpoints = no_tailnet_endpoints,
        on_attempt: Callable[[HubEndpoint], None] | None = None,
        discover_timeout_s: float = DISCOVER_TIMEOUT_S,
    ) -> None:
        self._paired_base_url = paired_base_url
        self._discover = discover
        self._try = try_endpoint
        self._tailnet = tailnet
        self._on_attempt = on_attempt
        self._discover_timeout_s = discover_timeout_s

    def _endpoints(self, failures: list[AttemptRecord]) -> Iterator[HubEndpoint]:
        """LAN entries, then tailnet entries; each source is asked only
        when the walk reaches it."""
        seen: set[str] = set()

        def fresh(endpoint: HubEndpoint) -> bool:
            if endpoint.base_url in seen:
                return False
            seen.add(endpoint.base_url)
            return True

        paired = self._paired_base_url()
        paired_endpoint = (
            HubEndpoint(classify_base_url(paired), paired, "paired") if paired else None
        )
        if paired_endpoint and paired_endpoint.kind is PathKind.LAN and fresh(paired_endpoint):
            yield paired_endpoint

        try:
            found = self._discover(timeout_s=self._discover_timeout_s)
        except Exception as exc:
            logger.warning("hub discovery failed during the walk", exc_info=True)
            placeholder = HubEndpoint(PathKind.LAN, "mdns", "mdns")
            failures.append(AttemptRecord(placeholder, False, f"discovery failed: {exc}"))
            found = None
        if found is not None:
            scheme = "https" if found.tls else "http"
            lan = HubEndpoint(
                PathKind.LAN,
                f"{scheme}://{found.host}:{found.port}",
                "mdns",
                instance_id=found.instance_id,
            )
            if fresh(lan):
                yield lan

        if paired_endpoint and paired_endpoint.kind is PathKind.TAILNET and fresh(paired_endpoint):
            yield paired_endpoint
        for entry in self._tailnet():
            if fresh(entry):
                yield entry

    def walk(self) -> WalkResult:
        result = WalkResult(answered=None)
        for endpoint in self._endpoints(result.attempts):
            if self._on_attempt is not None:
                self._on_attempt(endpoint)
            ok, error, *rest = self._try(endpoint)
            failure = None
            if not ok:
                failure = FailureKind(rest[0]) if rest and rest[0] else FailureKind.UNREACHABLE
            result.attempts.append(AttemptRecord(endpoint, ok, error, failure))
            if ok:
                result.answered = endpoint
                break
            if failure is FailureKind.REVOKED:
                # The hub itself said no: no other address gets the token.
                result.revoked = True
                break
        return result
