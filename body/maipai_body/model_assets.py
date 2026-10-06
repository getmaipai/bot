"""Verified local cache for assets synchronized from the paired hub."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_CHUNK_BYTES = 1 << 16


@dataclass(frozen=True)
class PinnedAsset:
    id: str
    file: str
    sha256: str
    unavailable_hint: str = ""


class AssetUnavailable(RuntimeError):
    """A pinned asset is not present in the authenticated hub manifest."""


class ChecksumMismatch(RuntimeError):
    """A cached file did not match its shared spec checksum."""


_hub_fetcher: Callable[[PinnedAsset, Path], Path] | None = None


def configure_asset_fetcher(fetcher: Callable[[PinnedAsset, Path], Path] | None) -> None:
    global _hub_fetcher
    _hub_fetcher = fetcher


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
    """Return a checksum-verified cache file, fetching it only from Home."""
    dest = asset_path(asset, cache_dir)
    if dest.is_file():
        if _sha256_of(dest) == asset.sha256:
            return dest
        dest.unlink()
    if _hub_fetcher is None:
        detail = f" {asset.unavailable_hint}" if asset.unavailable_hint else ""
        raise AssetUnavailable(f"{asset.file} needs a paired hub asset sync.{detail}")
    result = _hub_fetcher(asset, cache_dir)
    if not result.is_file() or _sha256_of(result) != asset.sha256:
        result.unlink(missing_ok=True)
        raise ChecksumMismatch(f"{asset.file}: hub asset failed its pinned sha256")
    return result
