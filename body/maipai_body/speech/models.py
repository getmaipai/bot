"""G2: the wake-word pipeline's model files, fetched on demand.

"Download, don't vendor": every file here is a pinned URL plus a sha256
checksum, fetched into a local cache directory and verified before use,
never tracked in this repo. The two front-end assets (melspectrogram,
embedding) are upstream openWakeWord, pinned to the same v0.5.1 release
and the same real checksums `home`'s own `wakewordAssets.ts` already
uses for its stock detector (home issue #185: that file's own recorded
checksums are each truncated by one hex character and can never verify;
the values below were independently recomputed against the actual
downloaded files, not copied from that file). The download-verify
mechanism itself lives in `maipai_body.model_assets` (extracted
2026-09-28 when vision's SFace model, FACE-01, needed the same
pattern) - the names below are kept as this module's own public API so
nothing that already imports from here breaks.
"""

from __future__ import annotations

from pathlib import Path

from maipai_body.model_assets import AssetUnavailable, PinnedAsset
from maipai_body.model_assets import ChecksumMismatch as ChecksumMismatch
from maipai_body.model_assets import asset_path as asset_path
from maipai_body.model_assets import ensure_asset as ensure_asset
from maipai_body.model_assets import is_installed as is_installed

_OWW_RELEASE_BASE = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"

WakewordAsset = PinnedAsset
WakewordModelUnavailable = AssetUnavailable


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
# WAKE_THRESHOLD in wake.py). Ships as a Bot release asset, never a
# tracked file (CLAUDE.md's Releases section), attached to v0.1.0.
# Fetching it needs the repo to be anonymously fetchable: a private
# repo's release asset URL 404s on a plain unauthenticated request (a
# real robot has no GitHub credentials, and shouldn't need any) - `bot`
# was made public for exactly this reason (2026-09-28, Jesse's call,
# after a full-history gitleaks and PII-wordlist scan came back clean).
WAKE_PHRASE = WakewordAsset(
    file="trained_hey_maipai_v2.onnx",
    url="https://github.com/getmaipai/bot/releases/download/v0.1.0/trained_hey_maipai_v2.onnx",
    sha256="6fbff74699801dabf931166badcc51fd655570469fb6d10da1ee5f64b4cba190",
    # A review (2026-09-28) caught the extraction to model_assets.py
    # silently dropping this operator guidance behind a generic
    # message - restored via PinnedAsset's own unavailable_hint, kept
    # here (not there) in case a future release ever pulls this asset
    # and the URL is cleared again.
    unavailable_hint=(
        "It's MaiPai's own trained model, which ships as a Bot release "
        "asset once one is cut. Until then, provide it locally (see "
        "docs/BACKLOG.md's G2 entry)."
    ),
)

ALL_ASSETS = (MELSPECTROGRAM, EMBEDDING, WAKE_PHRASE)


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
