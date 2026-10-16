"""The pinned move libraries: optional packages installed by Home.

"Download, don't vendor": ``pins.json`` names a full commit revision,
licence and sha256 per move file. Home installs this optional package;
the base robot never fetches directly from a dataset host.

Both Pollen libraries (emotions and dances, each Apache-2.0 on its
dataset card) are pinned the same way. A clip that leaves the profile's
envelope is listed under ``excluded`` with the reason and is never played
or clipped. ``clips`` is the clip index (name to description).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, field_validator, model_validator

from maipai_body.model_assets import AssetUnavailable

PINS_PATH = Path(__file__).with_name("pins.json")
_REVISION = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class LibraryPin(BaseModel, frozen=True):
    library: str
    repo: str
    revision: str
    license: str
    files: dict[str, str]  # move name -> sha256 of "<name>.json"
    excluded: dict[str, str] = {}  # move name -> why it is not playable
    clips: dict[str, str] = {}  # move name -> description (the clip index)

    @field_validator("revision")
    @classmethod
    def _full_revision(cls, value: str) -> str:
        if not _REVISION.fullmatch(value):
            raise ValueError("revision must be a full 40-character commit hash, never a branch")
        return value

    @field_validator("license")
    @classmethod
    def _apache_only(cls, value: str) -> str:
        if value != "Apache-2.0":
            raise ValueError("only Apache-2.0 libraries are pinned")
        return value

    @model_validator(mode="after")
    def _files_and_excluded_are_disjoint(self) -> LibraryPin:
        if set(self.files) & set(self.excluded):
            raise ValueError("a clip cannot be both pinned and excluded")
        return self


def load_pins(path: Path = PINS_PATH) -> list[LibraryPin]:
    return [LibraryPin(**entry) for entry in json.loads(path.read_text())["pins"]]


def ensure_move(pin: LibraryPin, name: str, cache_dir: Path) -> Path:
    """Return an installed optional move, never contacting its source repository."""
    if name in pin.excluded:
        raise AssetUnavailable(
            f"{name} is excluded from the {pin.library} library: {pin.excluded[name]}"
        )
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


def installed_names(pin: LibraryPin, cache_dir: Path) -> list[str]:
    """The pinned moves actually present (and verified) in ``cache_dir``.

    A robot with no pack installed has an empty cache and so no clip library.
    """
    found: list[str] = []
    for name in sorted(pin.files):
        try:
            ensure_move(pin, name, cache_dir)
        except AssetUnavailable:
            continue
        found.append(name)
    return found
