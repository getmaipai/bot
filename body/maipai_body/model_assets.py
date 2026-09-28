"""Pinned, checksummed third-party model files, fetched on demand.

"Download, don't vendor" (the org's own third-party-code rule): every
model this repo uses is a pinned URL plus a sha256 checksum, fetched
into a local cache directory and verified before use, never tracked in
this repo. Extracted from `speech/models.py` (G2's own wake-word
assets, the first user of this pattern) so a second domain (vision's
SFace model, FACE-01) doesn't duplicate the download-verify-atomic-
rename mechanism - one implementation, per the org's own first
principle, not a second copy that could drift.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import requests

_CHUNK_BYTES = 1 << 16


@dataclass(frozen=True)
class PinnedAsset:
    file: str
    url: str
    sha256: str
    # Appended to the "no pinned URL yet" error - a review (2026-09-28)
    # caught that extracting this module from speech/models.py had
    # silently dropped the wake phrase's own operator guidance ("it's
    # MaiPai's own trained model, ships as a release asset... see
    # docs/BACKLOG.md's G2 entry") behind a generic message. Each
    # asset supplies its own hint instead of this module guessing at
    # domain-specific advice; empty means the generic message alone.
    unavailable_hint: str = ""


class AssetUnavailable(RuntimeError):
    """A pinned asset isn't fetchable yet (no URL, or the fetch failed)."""


class ChecksumMismatch(RuntimeError):
    """A downloaded file's sha256 didn't match its pinned value."""


def asset_path(asset: PinnedAsset, cache_dir: Path) -> Path:
    return cache_dir / asset.file


def is_installed(asset: PinnedAsset, cache_dir: Path) -> bool:
    return asset_path(asset, cache_dir).exists()


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_asset(asset: PinnedAsset, cache_dir: Path) -> Path:
    """Downloads ``asset`` into ``cache_dir`` if not already present,
    verifying its checksum either way. Downloads to a ``.part`` sibling
    first and renames on success, so a killed download never leaves a
    file that looks installed but isn't."""
    if asset.url == "":
        message = f"{asset.file} has no pinned URL yet."
        if asset.unavailable_hint:
            message = f"{message} {asset.unavailable_hint}"
        raise AssetUnavailable(message)
    dest = asset_path(asset, cache_dir)
    if dest.exists():
        actual = _sha256_of(dest)
        if actual == asset.sha256:
            return dest
        dest.unlink()

    cache_dir.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(asset.url, stream=True, timeout=30) as response:
            response.raise_for_status()
            with part.open("wb") as f:
                for chunk in response.iter_content(chunk_size=_CHUNK_BYTES):
                    f.write(chunk)
    except requests.exceptions.RequestException as exc:
        part.unlink(missing_ok=True)
        raise AssetUnavailable(
            f"{asset.file} could not be fetched from {asset.url}: {exc}. "
            "Check the network connection; the first use needs this "
            "asset once, then reuses the cached copy offline."
        ) from exc

    actual = _sha256_of(part)
    if actual != asset.sha256:
        part.unlink()
        raise ChecksumMismatch(
            f"{asset.file}: sha256 {actual[:12]}... != expected {asset.sha256[:12]}..."
        )
    part.rename(dest)
    return dest
