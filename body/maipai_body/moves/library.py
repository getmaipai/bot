"""The pinned move libraries: a revision and a checksum per file, fetched on demand.

"Download, don't vendor": nothing from Pollen's libraries is tracked
here. ``pins.json`` names, per library, the dataset repo, a full commit
revision, its licence and a sha256 per move file; ``ensure_move`` fetches
one file through ``model_assets.ensure_asset`` (the repo's one
download-verify-rename mechanism) and refuses anything that does not
match. ``pins.json`` is written by ``body/scripts/pin_moves_library.py``
from the live dataset; it ships empty until that has been run with
network access, so every fetch fails with a clear "no pin" error rather
than trusting an unpinned file.

The dances library is excluded until its licence is stated.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, field_validator, model_validator

from maipai_body.model_assets import AssetUnavailable, PinnedAsset, ensure_asset

PINS_PATH = Path(__file__).with_name("pins.json")
EXCLUDED_LIBRARIES = {"dances": "licence unverified; excluded until Pollen states one"}
_REVISION = re.compile(r"[0-9a-f]{40}")


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


def move_url(pin: LibraryPin, name: str) -> str:
    return f"https://huggingface.co/datasets/{pin.repo}/resolve/{pin.revision}/{name}.json"


def ensure_move(pin: LibraryPin, name: str, cache_dir: Path) -> Path:
    """The verified local file for ``name``, fetched once and cached under the pin's revision."""
    if name not in pin.files:
        raise AssetUnavailable(f"{name} is not in the pinned {pin.library} library")
    asset = PinnedAsset(
        file=f"{pin.library}-{pin.revision[:12]}-{name}.json",
        url=move_url(pin, name),
        sha256=pin.files[name],
    )
    return ensure_asset(asset, cache_dir)
