"""G4: find the household's hub on the LAN via `_maipai._tcp`.

The wire contract is `home`'s own (`home/backend/src/lib/mdns.ts`):
service type `maipai` (`_maipai._tcp.local.` per DNS-SD), TXT fields
`id` (hub instance id), `name` (display name), `tls` ("1"/"0"),
`v` (record shape version, "1" today).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

logger = logging.getLogger("maipai_body.link.discovery")

SERVICE_TYPE = "_maipai._tcp.local."


class DiscoverHub(Protocol):
    """The shape both `client.py` and `lifecycle.py` depend on - real
    mDNS in production, a scripted fake in tests."""

    def __call__(self, timeout_s: float) -> HubAddress | None: ...


class HubAddress(BaseModel):
    """One hub found on the LAN, enough to attempt pairing."""

    host: str
    port: int
    instance_id: str
    name: str
    tls: bool


@dataclass
class _RawService:
    """What a real zeroconf `ServiceInfo` hands back - pulled into a
    plain dataclass so :func:`parse_service_info` is a pure function,
    testable without any real mDNS traffic."""

    addresses: list[str]
    port: int
    properties: dict[bytes, bytes | None]


def parse_service_info(raw: _RawService) -> HubAddress | None:
    """Parse one discovered service into a :class:`HubAddress`, or
    ``None`` if it's missing a field a client can't proceed without
    (no address, no instance id) - never raises on a malformed TXT
    record from a hub running a newer or older record shape."""
    if not raw.addresses:
        return None
    props = raw.properties
    instance_id = props.get(b"id")
    name = props.get(b"name")
    tls = props.get(b"tls")
    if instance_id is None:
        return None
    return HubAddress(
        host=raw.addresses[0],
        port=raw.port,
        instance_id=instance_id.decode("utf-8"),
        name=(name or b"").decode("utf-8", errors="replace"),
        tls=tls == b"1",
    )


def discover_hub(timeout_s: float = 5.0) -> HubAddress | None:
    """Browse for the first hub answering on `_maipai._tcp` within
    ``timeout_s``. Best-effort: a network that filters multicast, or
    any other responder failure, means no auto-discovery - never a
    crash (mirrors `home`'s own `advertiseMdns`'s failure posture)."""
    try:
        from zeroconf import Zeroconf
    except ImportError:
        logger.warning("zeroconf is not installed; cannot discover a hub")
        return None

    zc = Zeroconf()
    try:
        deadline = time.monotonic() + timeout_s
        names = _browse_service_names(zc, timeout_s)
        for name in names:
            remaining = max(0.1, deadline - time.monotonic())
            info = zc.get_service_info(SERVICE_TYPE, name, timeout=remaining * 1000)
            if info is None:
                continue
            raw = _RawService(
                addresses=info.parsed_addresses(),
                port=info.port or 0,
                properties=info.properties,
            )
            address = parse_service_info(raw)
            if address is not None:
                return address
        return None
    except Exception:
        logger.warning("hub discovery failed", exc_info=True)
        return None
    finally:
        zc.close()


def _browse_service_names(zc, timeout_s: float) -> list[str]:
    from zeroconf import ServiceBrowser

    found: list[str] = []

    class _Listener:
        def add_service(self, zeroconf, service_type, name) -> None:
            found.append(name)

        def update_service(self, zeroconf, service_type, name) -> None:
            pass

        def remove_service(self, zeroconf, service_type, name) -> None:
            pass

    browser = ServiceBrowser(zc, SERVICE_TYPE, _Listener())
    try:
        time.sleep(timeout_s)
    finally:
        browser.cancel()
    return found
