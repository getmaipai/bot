"""The pinned move libraries: optional packages installed by Home.

"Download, don't vendor": ``pins.json`` names a full commit revision,
licence and sha256 per move file. Home installs this optional package;
the base robot never fetches directly from a dataset host.

The dances library is excluded until its licence is stated.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, field_validator, model_validator

from maipai_body.model_assets import AssetUnavailable

PINS_PATH = Path(__file__).with_name("pins.json")
EXCLUDED_LIBRARIES = {"dances": "licence unverified; excluded until Pollen states one"}
_REVISION = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class LibraryPin(BaseModel, frozen=True):
    library: str
    repo: str
    revision: str
    license: str
    files: dict[str, str]  # move name -> sha256 of "<name>.json"

    @field_validator("revision")
    @classmethod
    def _full_revision(cls, value: str) -> str:
        if not _REVISION.fullmatch(value):
            raise ValueError("revision must be a full 40-character commit hash, never a branch")
        return value

    @model_validator(mode="after")
    def _not_excluded(self) -> LibraryPin:
        if self.library in EXCLUDED_LIBRARIES:
            raise ValueError(f"{self.library}: {EXCLUDED_LIBRARIES[self.library]}")
        return self


def load_pins(path: Path = PINS_PATH) -> list[LibraryPin]:
    return [LibraryPin(**entry) for entry in json.loads(path.read_text())["pins"]]


def ensure_move(pin: LibraryPin, name: str, cache_dir: Path) -> Path:
    """Return an installed optional move, never contacting its source repository."""
    if name not in pin.files:
        raise AssetUnavailable(f"{name} is not in the pinned {pin.library} library")
    if not _SHA256.fullmatch(pin.files[name]):
        # Refuse before any request: an unpinned file is never fetched.
        raise AssetUnavailable(f"{name} in the {pin.library} library has no valid sha256 pin")
    path = cache_dir / f"{pin.library}-{pin.revision[:12]}-{name}.json"
    candidates = [path]
    if cache_dir.is_dir():
        candidates.extend(
            candidate
            for candidate in cache_dir.rglob("*.json")
            if candidate != path and candidate.is_file()
        )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if digest == pin.files[name]:
            return candidate
    if path.exists():
        path.unlink()
    raise AssetUnavailable(
        f"{name} is not installed or failed its checksum; install the optional moves package "
        "through Home"
    )
