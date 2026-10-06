"""Wake-word asset pins resolve through the paired hub cache."""

from __future__ import annotations

import hashlib

import pytest

from maipai_body.model_assets import (
    AssetUnavailable,
    ChecksumMismatch,
    configure_asset_fetcher,
    ensure_asset,
)
from maipai_body.speech.models import (
    ALL_ASSETS,
    EMBEDDING,
    MELSPECTROGRAM,
    WAKE_PHRASE,
    ensure_wakeword_models,
)


@pytest.fixture(autouse=True)
def clear_asset_fetcher():
    configure_asset_fetcher(None)
    yield
    configure_asset_fetcher(None)


def test_wakeword_assets_use_shared_spec_ids_and_checksums():
    assert [asset.id for asset in ALL_ASSETS] == [
        "openwakeword-melspectrogram-v0_5_1",
        "openwakeword-embedding-v0_5_1",
        "hey-maipai-v2",
    ]
    assert all(len(asset.sha256) == 64 for asset in ALL_ASSETS)


def test_ensure_asset_uses_configured_hub_fetcher_and_caches(tmp_path):
    content = b"hub supplied model"
    asset = type(MELSPECTROGRAM)("test-model", "model.onnx", hashlib.sha256(content).hexdigest())
    calls = []

    def fetch(current, cache_dir):
        calls.append(current.id)
        path = cache_dir / current.file
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    configure_asset_fetcher(fetch)
    result = ensure_asset(asset, tmp_path)
    assert result.read_bytes() == content
    assert ensure_asset(asset, tmp_path) == result
    assert calls == ["test-model"]


def test_bad_hub_bytes_are_removed_and_refused(tmp_path):
    asset = type(MELSPECTROGRAM)("test-model", "model.onnx", "0" * 64)

    def fetch(current, cache_dir):
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / current.file
        path.write_bytes(b"tampered")
        return path

    configure_asset_fetcher(fetch)
    with pytest.raises(ChecksumMismatch, match="hub asset failed"):
        ensure_asset(asset, tmp_path)
    assert not (tmp_path / asset.file).exists()


def test_first_use_without_a_paired_hub_fails_clearly(tmp_path):
    with pytest.raises(AssetUnavailable, match="paired hub asset sync"):
        ensure_asset(WAKE_PHRASE, tmp_path)


def test_wakeword_models_request_all_three_pinned_assets(tmp_path, monkeypatch):
    import maipai_body.speech.models as models

    seen = []

    def fake_ensure(asset, cache_dir):
        seen.append(asset.id)
        return cache_dir / asset.file

    monkeypatch.setattr(models, "ensure_asset", fake_ensure)
    paths = ensure_wakeword_models(tmp_path)
    assert set(paths) == {MELSPECTROGRAM.file, EMBEDDING.file, WAKE_PHRASE.file}
    assert seen == [asset.id for asset in ALL_ASSETS]
