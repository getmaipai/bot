"""Local administrator approval and per-device bearer tokens."""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

LOG = logging.getLogger(__name__)
_MAC = re.compile(r"^[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
PENDING_LIMIT = 8
PENDING_TTL = 600
ENROLLMENT_LIMIT = 32


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
        self._enrollments: dict[str, dict[str, object]] = {}
        self._pending: dict[tuple[str, str], PairingRequest] = {}
        self._file_signature: tuple[int, int] | None = None
        with self._lock:
            with self._file_lock():
                self._refresh()

    @contextmanager
    def _file_lock(self):
        """Serialize read-modify-write across the service and dashboard processes."""
        if self.path is None:
            yield
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _valid_id(device_id: str) -> bool:
        return bool(_MAC.fullmatch(device_id))

    @staticmethod
    def _valid_client_id(client_id: str) -> bool:
        return bool(_UUID.fullmatch(client_id))

    def authorize(self, device_id: str, client_id: str, token: str | None) -> bool:
        if not self._valid_id(device_id) or not token:
            return False
        with self._lock:
            self._refresh()
            record = self._devices.get(device_id)
            if not record or record.get("client_id") != client_id:
                return False
            digest = hashlib.sha256(token.encode()).hexdigest()
            return secrets.compare_digest(str(record.get("token_sha256", "")), digest)

    def issue_enrollment(self, ttl: int = 86400) -> tuple[str, str]:
        if ttl <= 0:
            raise ValueError("Enrollment lifetime must be positive.")
        code_id, code = secrets.token_hex(8), secrets.token_urlsafe(24)
        with self._lock:
            with self._file_lock():
                self._refresh()
                live = sum(
                    not enrollment.get("spent")
                    and float(enrollment.get("expires_at", 0)) > time.time()
                    for enrollment in self._enrollments.values()
                )
                if live >= ENROLLMENT_LIMIT:
                    raise RuntimeError(
                        "Too many unfinished installs. Cancel an unfinished install and retry."
                    )
                self._enrollments[code_id] = {
                    "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
                    "expires_at": time.time() + ttl,
                    "bound_device": None,
                    "bound_client": None,
                    "spent": False,
                }
                self._save()
        return code_id, code

    def redeem_enrollment(self, device_id: str, client_id: str, code: str | None) -> str | None:
        if not self._valid_id(device_id) or not self._valid_client_id(client_id) or not code:
            return None
        digest = hashlib.sha256(code.encode()).hexdigest()
        with self._lock:
            with self._file_lock():
                self._refresh()
                now = time.time()
                for code_id, enrollment in self._enrollments.items():
                    if enrollment.get("spent") or float(enrollment.get("expires_at", 0)) <= now:
                        continue
                    if not secrets.compare_digest(str(enrollment.get("code_sha256", "")), digest):
                        continue
                    bound = enrollment.get("bound_device")
                    if bound is not None and (
                        bound != device_id or enrollment.get("bound_client") != client_id
                    ):
                        return None
                    existing = self._devices.get(device_id)
                    if existing is not None and existing.get("enrollment_id") != code_id:
                        return None
                    enrollment["bound_device"] = device_id
                    enrollment["bound_client"] = client_id
                    token = secrets.token_urlsafe(32)
                    self._devices[device_id] = {
                        "client_id": client_id,
                        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                        "approved_at": now,
                        "enrollment_id": code_id,
                    }
                    self._save()
                    return token
        return None

    def revoke_enrollment(self, code_id: str) -> bool:
        with self._lock:
            with self._file_lock():
                self._refresh()
                enrollment = self._enrollments.pop(code_id, None)
                if enrollment and enrollment.get("bound_device"):
                    device_id = str(enrollment["bound_device"])
                    device = self._devices.get(device_id)
                    if device and device.get("enrollment_id") == code_id:
                        self._devices.pop(device_id, None)
                self._save()
                return enrollment is not None

    def enrollment(self, code_id: str) -> dict[str, object] | None:
        with self._lock:
            self._refresh()
            record = self._enrollments.get(code_id)
            return dict(record) if record else None

    def spend_enrollment(self, device_id: str) -> None:
        with self._lock:
            with self._file_lock():
                self._refresh()
                device = self._devices.get(device_id)
                enrollment_id = device.get("enrollment_id") if device else None
                record = self._enrollments.get(str(enrollment_id))
                if record is not None and not record.get("spent"):
                    record["spent"] = True
                    self._save()

    @staticmethod
    def _pending_key(device_id: str, client_id: str) -> tuple[str, str]:
        return device_id, client_id

    def recognizes_device(self, device_id: str, client_id: str) -> bool:
        """Whether this identity has an approved or pending pairing record."""
        with self._lock:
            self._refresh()
            self._expire_pending()
            record = self._devices.get(device_id)
            return (record is not None and record.get("client_id") == client_id) or (
                self._pending_key(device_id, client_id) in self._pending
            )

    def request(self, device_id: str, client_id: str) -> PairingRequest:
        if not self._valid_id(device_id) or not self._valid_client_id(client_id):
            raise ValueError(
                "Device-Id must be a MAC address and Client-Id must be a UUID. Correct both "
                "headers and reconnect."
            )
        with self._lock:
            with self._file_lock():
                self._refresh()
                self._expire_pending()
                req = PairingRequest(
                    device_id=device_id, client_id=client_id, requested_at=time.time()
                )
                key = self._pending_key(device_id, client_id)
                if key not in self._pending and len(self._pending) >= PENDING_LIMIT:
                    raise ValueError(
                        "The pending pairing list is full. Approve or remove a pending device, "
                        "then reconnect."
                    )
                self._pending[key] = req
                self._save()
                return req

    def approve(self, device_id: str, client_id: str) -> str:
        """Approve a pending device and return its one-time token."""
        with self._lock:
            with self._file_lock():
                self._refresh()
                self._expire_pending()
                req = self._pending.pop(self._pending_key(device_id, client_id), None)
                if req is None:
                    raise KeyError(
                        "No pending request matches this Device-Id and Client-Id. Copy both values "
                        "from the pending list, then approve again."
                    )
                token = secrets.token_urlsafe(32)
                self._devices[device_id] = {
                    "client_id": req.client_id,
                    "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                    "approved_at": time.time(),
                }
                self._save()
                return token

    def approve_to_file(self, device_id: str, client_id: str) -> Path:
        """Approve a device and place its one-time token in a private local file."""
        token = self.approve(device_id, client_id)
        base = self.path.parent if self.path else Path.home() / ".local/share/maipai-bot"
        directory = base / "stackchan-tokens"
        path = directory / f"{secrets.token_hex(12)}.token"
        try:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as token_file:
                token_file.write(token)
                token_file.write("\n")
        except OSError:
            self.revoke(device_id)
            raise
        return path

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            with self._file_lock():
                self._refresh()
                removed = self._devices.pop(device_id, None) is not None
                for key in [key for key in self._pending if key[0] == device_id]:
                    self._pending.pop(key, None)
                self._save()
                return removed

    def pending(self) -> tuple[PairingRequest, ...]:
        with self._lock:
            self._refresh()
            self._expire_pending()
            return tuple(self._pending.values())

    def allowed_device_ids(self) -> frozenset[str]:
        with self._lock:
            self._refresh()
            return frozenset(self._devices)

    def _expire_pending(self) -> None:
        now = time.time()
        expired = [
            key
            for key, request in self._pending.items()
            if now - request.requested_at > PENDING_TTL
        ]
        for key in expired:
            self._pending.pop(key, None)

    def _refresh(self) -> None:
        if self.path is None:
            return
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            signature = None
        else:
            signature = (stat.st_mtime_ns, stat.st_size)
        if signature == self._file_signature:
            return
        if signature is None:
            self._devices = {}
            self._enrollments = {}
            self._pending = {}
            self._file_signature = None
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            devices = raw.get("devices", {})
            enrollments = raw.get("enrollments", {})
            pending = {
                self._pending_key(request["device_id"], request["client_id"]): PairingRequest(
                    device_id=request["device_id"],
                    client_id=request["client_id"],
                    requested_at=float(request["requested_at"]),
                )
                for request in raw.get("pending", {}).values()
            }
            if (
                not isinstance(devices, dict)
                or not isinstance(pending, dict)
                or not isinstance(enrollments, dict)
            ):
                raise TypeError("pairing data must contain device, enrollment and pending objects")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError) as exc:
            LOG.error(
                "Pairing file %s is corrupt (%s). Move it aside and reapprove devices.",
                self.path,
                type(exc).__name__,
            )
            self._devices = {}
            self._enrollments = {}
            self._pending = {}
            self._file_signature = signature
            return
        self._devices = devices
        self._enrollments = enrollments
        self._prune_enrollments()
        self._pending = pending
        self._expire_pending()
        self._file_signature = signature

    def _save(self) -> None:
        if self.path is None:
            return
        self._prune_enrollments()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f"{self.path.name}.tmp.{os.getpid()}.{secrets.token_hex(6)}")
        data = {
            "devices": self._devices,
            "enrollments": self._enrollments,
            "pending": {
                f"{request.device_id}|{request.client_id}": {
                    "device_id": request.device_id,
                    "client_id": request.client_id,
                    "requested_at": request.requested_at,
                }
                for device_id, request in self._pending.items()
            },
        }
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as pairing_file:
            pairing_file.write(json.dumps(data, sort_keys=True) + "\n")
        temp.chmod(0o600)
        temp.replace(self.path)
        stat = self.path.stat()
        self._file_signature = (stat.st_mtime_ns, stat.st_size)

    def _prune_enrollments(self) -> None:
        now = time.time()
        referenced = {
            str(device.get("enrollment_id"))
            for device in self._devices.values()
            if isinstance(device, dict) and device.get("enrollment_id") is not None
        }
        kept = {}
        for code_id, enrollment in self._enrollments.items():
            if not isinstance(enrollment, dict):
                continue
            try:
                expires_at = float(enrollment.get("expires_at", 0))
            except (TypeError, ValueError):
                continue
            if expires_at <= now and enrollment.get("bound_device") is None:
                continue
            if enrollment.get("spent") and code_id not in referenced:
                continue
            kept[code_id] = enrollment
        self._enrollments = kept


def default_pairing_path() -> Path:
    """Return the local file shared by the service and dashboard process."""
    data_dir = Path(
        os.environ.get("MAIPAI_BOT_DATA_DIR") or Path.home() / ".local/share/maipai-bot"
    )
    return data_dir / "stackchan-pairing.json"
