"""G4: the persisted hub pairing, one file, sealed at the OS level.

Ported in shape (not code - "download, don't vendor") from the legacy
`robot/robot/hublink/pairing.py`'s `HubPairingStore`: one pairing, one
file, atomic replace, fail-soft (a corrupt file reads as "not paired,"
never a crash). Deliberately simpler than legacy's own version: legacy
sealed the record under a device-key `SecretBox` (its own crypto
module, not carried into this rebuild); this store relies on the
file's own `0o600` permission bit instead - the same protection class
an SSH private key gets, and the only thing the gap-audit's own G4
acceptance actually requires ("the token file is 0o600"). Real
encryption-at-rest for this specific file is a real, separate
hardening item if the org wants it later, not something to half-build
here by copying legacy's crypto machinery uncritically.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel


class HubPairing(BaseModel):
    """What survives a reboot: enough to redeem a session without
    repairing. ``fingerprint`` pins the hub's TLS identity across
    address changes (a DHCP lease, a tailnet reconnect) - a hub
    presenting a different one is refused, not silently trusted."""

    base_url: str
    device_token: str  # the credential; never logged, never put on a response
    hub_instance_id: str
    fingerprint: str | None = None  # None only for a plain-http LAN pairing


def _private_opener(path: str, flags: int) -> int:
    return os.open(path, flags, 0o600)


class PairingStore:
    """One pairing, one file. :meth:`load` returns ``None`` when unpaired
    or unreadable; :meth:`save` replaces atomically; :meth:`clear`
    unpairs."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> HubPairing | None:
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return HubPairing.model_validate(data)
        except Exception:
            return None

    def save(self, pairing: HubPairing) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8", opener=_private_opener) as f:
            f.write(pairing.model_dump_json())
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)

    def clear(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
