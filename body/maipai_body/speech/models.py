"""G2: the wake-word pipeline's model files, fetched on demand.

"Download, don't vendor": every file here is a pinned URL plus a sha256
checksum, fetched into a local cache directory and verified before use,
never tracked in this repo. The two front-end assets (melspectrogram,
embedding) are upstream openWakeWord, pinned to the same v0.5.1 release
and the same real checksums `home`'s own `wakewordAssets.ts` already
uses for its stock detector (home issue #185: that file's own recorded
checksums are each truncated by one hex character and can never verify;
the values below were independently recomputed against the actual
downloaded files, not copied from that file).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import requests

_OWW_RELEASE_BASE = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"

_CHUNK_BYTES = 1 << 16


@dataclass(frozen=True)
class WakewordAsset:
    file: str
    url: str
    sha256: str


# Shared by every detector - required before any wake-word inference can run.
MELSPECTROGRAM = WakewordAsset(
    file="melspectrogram.onnx",
    url=f"{_OWW_RELEASE_BASE}/melspectrogram.onnx",
    sha256="ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f",
)
EMBEDDING = WakewordAsset(
    file="embedding_model.onnx",
    url=f"{_OWW_RELEASE_BASE}/embedding_model.onnx",
    sha256="70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f",
)

# MaiPai's own trained "hey maipai" classifier (v2, threshold 0.8; see
# WAKE_THRESHOLD in wake.py). Not yet a real URL: this is MaiPai's own
# artifact, which per CLAUDE.md's Releases section ships as a release
# asset, never a tracked file - and cutting that release is Jesse's own
# call, not something a session does unilaterally. Until a Bot release
# carries it, WAKE_PHRASE.url is a placeholder and fetching it raises a
# clear error naming exactly what's missing, not a broken download.
WAKE_PHRASE_PENDING_RELEASE = True
WAKE_PHRASE = WakewordAsset(
    file="trained_hey_maipai_v2.onnx",
    url="",
    sha256="6fbff74699801dabf931166badcc51fd655570469fb6d10da1ee5f64b4cba190",
)

ALL_ASSETS = (MELSPECTROGRAM, EMBEDDING, WAKE_PHRASE)


class WakewordModelUnavailable(RuntimeError):
    """A pinned model isn't fetchable yet (no release asset exists)."""


class ChecksumMismatch(RuntimeError):
    """A downloaded file's sha256 didn't match its pinned value."""


def asset_path(asset: WakewordAsset, cache_dir: Path) -> Path:
    return cache_dir / asset.file


def is_installed(asset: WakewordAsset, cache_dir: Path) -> bool:
    return asset_path(asset, cache_dir).exists()


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_asset(asset: WakewordAsset, cache_dir: Path) -> Path:
    """Downloads ``asset`` into ``cache_dir`` if not already present,
    verifying its checksum either way. Downloads to a ``.part`` sibling
    first and renames on success, so a killed download never leaves a
    file that looks installed but isn't."""
    if asset.url == "":
        raise WakewordModelUnavailable(
            f"{asset.file} has no pinned URL yet - it's MaiPai's own trained "
            "model, which ships as a Bot release asset once one is cut. "
            "Until then, provide it locally (see docs/BACKLOG.md's G2 entry)."
        )
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
        raise WakewordModelUnavailable(
            f"{asset.file} could not be fetched from {asset.url}: {exc}. "
            "Check the network connection; wake word needs this asset "
            "the first time, then reuses the cached copy offline."
        ) from exc

    actual = _sha256_of(part)
    if actual != asset.sha256:
        part.unlink()
        raise ChecksumMismatch(
            f"{asset.file}: sha256 {actual[:12]}... != expected {asset.sha256[:12]}..."
        )
    part.rename(dest)
    return dest


def ensure_wakeword_models(cache_dir: Path) -> dict[str, Path]:
    """Fetches the two shared front-end assets; the wake phrase is
    fetched too if its URL is pinned, otherwise omitted from the result
    (callers needing it get :class:`WakewordModelUnavailable`, not a
    silent gap)."""
    paths = {
        MELSPECTROGRAM.file: ensure_asset(MELSPECTROGRAM, cache_dir),
        EMBEDDING.file: ensure_asset(EMBEDDING, cache_dir),
    }
    if WAKE_PHRASE.url:
        paths[WAKE_PHRASE.file] = ensure_asset(WAKE_PHRASE, cache_dir)
    return paths
