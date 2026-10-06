"""Wake-word pins read from the shared spec and fetched from Home."""

from __future__ import annotations

from pathlib import Path

from maipai_body.link.assets import pinned_asset
from maipai_body.model_assets import AssetUnavailable, PinnedAsset
from maipai_body.model_assets import ChecksumMismatch as ChecksumMismatch
from maipai_body.model_assets import asset_path as asset_path
from maipai_body.model_assets import ensure_asset as ensure_asset
from maipai_body.model_assets import is_installed as is_installed

WakewordAsset = PinnedAsset
WakewordModelUnavailable = AssetUnavailable


# Shared by every detector - required before any wake-word inference can run.
MELSPECTROGRAM = pinned_asset("openwakeword-melspectrogram-v0_5_1")
EMBEDDING = pinned_asset("openwakeword-embedding-v0_5_1")

# MaiPai's trained wake phrase classifier. The hub serves the bytes by
# the spec asset id; the robot has no third-party download path.
WAKE_PHRASE = pinned_asset(
    "hey-maipai-v2",
    unavailable_hint="This model is pinned in the shared robot asset list; install it from Home.",
)

ALL_ASSETS = (MELSPECTROGRAM, EMBEDDING, WAKE_PHRASE)


def ensure_wakeword_models(cache_dir: Path) -> dict[str, Path]:
    """Fetches the two shared front-end assets; the wake phrase is
    and wake phrase from the paired hub."""
    paths = {
        MELSPECTROGRAM.file: ensure_asset(MELSPECTROGRAM, cache_dir),
        EMBEDDING.file: ensure_asset(EMBEDDING, cache_dir),
    }
    paths[WAKE_PHRASE.file] = ensure_asset(WAKE_PHRASE, cache_dir)
    return paths
