"""Local administrator approval and per-device bearer tokens."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock


@dataclass(frozen=True)
class PairingRequest:
    device_id: str
    client_id: str
    requested_at: float


class PairingRequired(PermissionError):
    """Raised when an unapproved device asks to connect."""


class PairingStore:
    """Stores an allowlist and one-way token digests in a local JSON file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._lock = RLock()
        self._devices: dict[str, dict[str, str | float]] = {}
        self._pending: dict[str, PairingRequest] = {}
        if self.path and self.path.exists():
            raw = json.loads(self.path.read_text())
            self._devices = raw.get("devices", {})

    @staticmethod
    def _valid_id(device_id: str) -> bool:
        return bool(device_id) and len(device_id) <= 128 and all(c.isprintable() for c in device_id)

    def authorize(self, device_id: str, client_id: str, token: str | None) -> bool:
        if not self._valid_id(device_id) or not token:
            return False
        with self._lock:
            record = self._devices.get(device_id)
            if not record or record.get("client_id") != client_id:
                return False
            digest = hashlib.sha256(token.encode()).hexdigest()
            return secrets.compare_digest(str(record.get("token_sha256", "")), digest)

    def request(self, device_id: str, client_id: str) -> PairingRequest:
        if not self._valid_id(device_id) or not self._valid_id(client_id):
            raise ValueError(
                "Device-Id and Client-Id must be printable identifiers, each no longer than "
                "128 characters."
            )
        with self._lock:
            req = PairingRequest(device_id=device_id, client_id=client_id, requested_at=time.time())
            self._pending[device_id] = req
            return req

    def approve(self, device_id: str) -> str:
        """Approve a pending device and return its only plaintext token copy."""
        with self._lock:
            req = self._pending.pop(device_id, None)
            if req is None:
                raise KeyError(
                    "No pending pairing request for this device. Ask it to reconnect, then "
                    "approve it."
                )
            token = secrets.token_urlsafe(32)
            self._devices[device_id] = {
                "client_id": req.client_id,
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "approved_at": req.requested_at,
            }
            self._save()
            return token

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            removed = self._devices.pop(device_id, None) is not None
            self._save()
            return removed

    def pending(self) -> tuple[PairingRequest, ...]:
        with self._lock:
            return tuple(self._pending.values())

    def allowed_device_ids(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._devices)

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps({"devices": self._devices}, sort_keys=True) + "\n")
        temp.chmod(0o600)
        temp.replace(self.path)
