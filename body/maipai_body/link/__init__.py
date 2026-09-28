"""G4: the robot's own hub link - discovery, pairing, and the persisted
device token that lets it survive a reboot without repairing."""

from __future__ import annotations

from maipai_body.link.client import HubLinkClient, PairingResult
from maipai_body.link.discovery import HubAddress, discover_hub
from maipai_body.link.store import HubPairing, PairingStore

__all__ = [
    "HubAddress",
    "HubLinkClient",
    "HubPairing",
    "PairingResult",
    "PairingStore",
    "discover_hub",
]
