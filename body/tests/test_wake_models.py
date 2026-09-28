"""G2's own acceptance: pinned wake-word assets download and verify."""

from __future__ import annotations

import functools
import hashlib
import http.server
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from maipai_body.speech.models import (
    ChecksumMismatch,
    WakewordAsset,
    WakewordModelUnavailable,
    ensure_asset,
    ensure_wakeword_models,
    is_installed,
)


@pytest.fixture
def local_asset_server(tmp_path):
    """A real HTTP server over a temp directory, in-process - proves the
    real download+checksum path against real HTTP, not a mocked call."""
    served_dir = tmp_path / "served"
    served_dir.mkdir()

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(served_dir))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield served_dir, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _write_and_hash(path: Path, content: bytes) -> str:
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def test_ensure_asset_downloads_and_verifies(local_asset_server, tmp_path):
    served_dir, base_url = local_asset_server
    content = b"a fake onnx model, just bytes for the checksum path"
    digest = _write_and_hash(served_dir / "model.onnx", content)
    asset = WakewordAsset(file="model.onnx", url=f"{base_url}/model.onnx", sha256=digest)
    cache_dir = tmp_path / "cache"

    result = ensure_asset(asset, cache_dir)

    assert result == cache_dir / "model.onnx"
    assert result.read_bytes() == content
    assert is_installed(asset, cache_dir)


def test_ensure_asset_is_idempotent_and_skips_a_second_download(local_asset_server, tmp_path):
    served_dir, base_url = local_asset_server
    content = b"same bytes every time"
    digest = _write_and_hash(served_dir / "model.onnx", content)
    asset = WakewordAsset(file="model.onnx", url=f"{base_url}/model.onnx", sha256=digest)
    cache_dir = tmp_path / "cache"
    ensure_asset(asset, cache_dir)
    mtime_before = (cache_dir / "model.onnx").stat().st_mtime_ns

    # Remove the served copy - a second ensure_asset() must not need it,
    # since the cached file's own checksum already matches.
    (served_dir / "model.onnx").unlink()
    result = ensure_asset(asset, cache_dir)

    assert result.stat().st_mtime_ns == mtime_before


def test_ensure_asset_raises_and_cleans_up_on_a_checksum_mismatch(local_asset_server, tmp_path):
    served_dir, base_url = local_asset_server
    (served_dir / "model.onnx").write_bytes(b"not what the pin expects")
    asset = WakewordAsset(file="model.onnx", url=f"{base_url}/model.onnx", sha256="0" * 64)
    cache_dir = tmp_path / "cache"

    with pytest.raises(ChecksumMismatch):
        ensure_asset(asset, cache_dir)

    assert not is_installed(asset, cache_dir)
    assert not (cache_dir / "model.onnx.part").exists()


def test_ensure_asset_redownloads_a_locally_corrupted_cache_entry(local_asset_server, tmp_path):
    served_dir, base_url = local_asset_server
    content = b"the real content"
    digest = _write_and_hash(served_dir / "model.onnx", content)
    asset = WakewordAsset(file="model.onnx", url=f"{base_url}/model.onnx", sha256=digest)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "model.onnx").write_bytes(b"corrupted, wrong bytes")

    result = ensure_asset(asset, cache_dir)

    assert result.read_bytes() == content


def test_an_asset_with_no_pinned_url_raises_a_named_error(tmp_path):
    asset = WakewordAsset(file="pending.onnx", url="", sha256="0" * 64)

    with pytest.raises(WakewordModelUnavailable):
        ensure_asset(asset, tmp_path)


def test_wake_phrase_carries_its_own_operator_guidance_if_unpinned(tmp_path, monkeypatch):
    """A review (2026-09-28) caught the model_assets.py extraction
    silently dropping this asset's own operator-facing guidance behind
    a generic message - this proves it survives, not just that some
    error is raised."""
    import maipai_body.speech.models as models_module

    monkeypatch.setattr(models_module, "WAKE_PHRASE", replace(models_module.WAKE_PHRASE, url=""))

    with pytest.raises(WakewordModelUnavailable, match="docs/BACKLOG.md's G2 entry"):
        ensure_asset(models_module.WAKE_PHRASE, tmp_path)


def test_a_network_failure_raises_a_clear_error_not_a_raw_requests_exception(tmp_path):
    """The org standard for a third-party model fetch: 'a clear failure
    message when offline,' not a bare socket/DNS traceback."""
    # Port 1 is a reserved, never-listening port - a fast, reliable way
    # to trigger a real connection failure without depending on the
    # network actually being down.
    asset = WakewordAsset(file="model.onnx", url="http://127.0.0.1:1/model.onnx", sha256="0" * 64)

    with pytest.raises(WakewordModelUnavailable, match="could not be fetched"):
        ensure_asset(asset, tmp_path)

    assert not (tmp_path / "model.onnx.part").exists()


def _patch_front_end(monkeypatch, models_module, served_dir, base_url):
    mel_content = b"melspectrogram bytes"
    emb_content = b"embedding bytes"
    mel_digest = _write_and_hash(served_dir / "melspectrogram.onnx", mel_content)
    emb_digest = _write_and_hash(served_dir / "embedding_model.onnx", emb_content)
    monkeypatch.setattr(
        models_module,
        "MELSPECTROGRAM",
        replace(
            models_module.MELSPECTROGRAM,
            url=f"{base_url}/melspectrogram.onnx",
            sha256=mel_digest,
        ),
    )
    monkeypatch.setattr(
        models_module,
        "EMBEDDING",
        replace(models_module.EMBEDDING, url=f"{base_url}/embedding_model.onnx", sha256=emb_digest),
    )
    return mel_content, emb_content


def test_ensure_wakeword_models_fetches_the_shared_front_end_and_the_wake_phrase(
    local_asset_server, tmp_path, monkeypatch
):
    """When every asset has a pinned URL (the real case since v0.1.0
    shipped the trained model as a release asset), all three are
    fetched - the wake phrase is no longer a special case."""
    served_dir, base_url = local_asset_server
    import maipai_body.speech.models as models_module

    mel_content, emb_content = _patch_front_end(monkeypatch, models_module, served_dir, base_url)
    wake_content = b"trained wake phrase bytes"
    wake_digest = _write_and_hash(served_dir / "trained_hey_maipai_v2.onnx", wake_content)
    monkeypatch.setattr(
        models_module,
        "WAKE_PHRASE",
        replace(
            models_module.WAKE_PHRASE,
            url=f"{base_url}/trained_hey_maipai_v2.onnx",
            sha256=wake_digest,
        ),
    )

    cache_dir = tmp_path / "cache"
    paths = ensure_wakeword_models(cache_dir)

    assert paths["melspectrogram.onnx"].read_bytes() == mel_content
    assert paths["embedding_model.onnx"].read_bytes() == emb_content
    assert paths["trained_hey_maipai_v2.onnx"].read_bytes() == wake_content


def test_ensure_wakeword_models_omits_a_wake_phrase_with_no_pinned_url(
    local_asset_server, tmp_path, monkeypatch
):
    """A caller that only needs the shared front-end (or a future
    detector genuinely without a release yet) isn't forced to fail for
    a wake phrase it didn't ask about."""
    served_dir, base_url = local_asset_server
    import maipai_body.speech.models as models_module

    mel_content, emb_content = _patch_front_end(monkeypatch, models_module, served_dir, base_url)
    monkeypatch.setattr(models_module, "WAKE_PHRASE", replace(models_module.WAKE_PHRASE, url=""))

    cache_dir = tmp_path / "cache"
    paths = ensure_wakeword_models(cache_dir)

    assert paths["melspectrogram.onnx"].read_bytes() == mel_content
    assert paths["embedding_model.onnx"].read_bytes() == emb_content
    assert "trained_hey_maipai_v2.onnx" not in paths
