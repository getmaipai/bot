from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import requests

from maipai_body.link.assets import AssetSync, AssetSyncError


class Response:
    def __init__(self, *, payload=None, content=b"", status=200):
        self.payload = payload
        self.content = content
        self.status_code = status
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Session:
    def __init__(self, manifest, data):
        self.manifest = manifest
        self.data = data
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith("/assets"):
            return Response(payload={"assets": self.manifest})
        asset_id = url.rsplit("/", 1)[-1]
        return Response(content=self.data[asset_id])


def _entry(asset_id: str, filename: str, body: bytes) -> dict:
    return {
        "id": asset_id,
        "file": filename,
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "licence": "Apache-2.0",
        "kind": "model",
    }


def _pin_file(tmp_path: Path, entry: dict) -> Path:
    path = tmp_path / "robot-assets.json"
    path.write_text(__import__("json").dumps([entry]))
    return path


def _spec_entry(entry: dict) -> dict:
    return {
        **entry,
        "source_url": "https://unused.invalid",
        "bytes": entry["bytes"],
    }


def test_asset_sync_uses_only_authenticated_hub_routes_and_verifies_bytes(tmp_path):
    body = b"hub-provided-model"
    entry = _entry("model-a", "model.onnx", body)
    session = Session([entry], {"model-a": body})
    sync = AssetSync(
        "http://hub.test",
        "session=secret",
        session=session,
        spec_path=_pin_file(tmp_path, _spec_entry(entry)),
    )

    result = sync.sync(tmp_path)

    assert result["model-a"].read_bytes() == body
    assert session.calls == [
        "http://hub.test/api/devices/me/assets",
        "http://hub.test/api/devices/me/assets/model-a",
    ]


def test_asset_sync_refuses_bad_checksum_and_does_not_install_file(tmp_path):
    entry = _entry("model-a", "model.onnx", b"expected")
    session = Session([entry], {"model-a": b"tampered"})
    sync = AssetSync(
        "http://hub.test",
        "session=secret",
        session=session,
        spec_path=_pin_file(tmp_path, _spec_entry(entry)),
    )

    with pytest.raises(AssetSyncError, match="checksum"):
        sync.sync(tmp_path)

    assert not (tmp_path / "model.onnx").exists()
    assert not (tmp_path / "model.onnx.part").exists()


def test_asset_sync_rejects_path_traversal(tmp_path):
    entry = _entry("model-a", "../outside.onnx", b"x")
    session = Session([entry], {"model-a": b"x"})
    sync = AssetSync(
        "http://hub.test",
        "session=secret",
        session=session,
        spec_path=_pin_file(tmp_path, _spec_entry(entry)),
    )

    with pytest.raises(AssetSyncError, match="unsafe"):
        sync.sync(tmp_path)


def test_asset_sync_installs_available_clip_bundle_with_verified_sidecar(tmp_path):
    body = b"clip archive"
    entry = _entry("clip-bundle-v1", "offline-clips-v1.zip", body)
    entry["kind"] = "clip_bundle"
    entry["licence"] = "AGPL-3.0"
    entry["available"] = True
    session = Session([entry], {"clip-bundle-v1": body})
    spec = tmp_path / "robot-assets.json"
    spec.write_text("[]")
    sync = AssetSync("http://hub.test", "session=secret", session=session, spec_path=spec)

    result = sync.sync(tmp_path / "cache")

    assert result["clip-bundle-v1"].read_bytes() == body
    assert (
        '"kind": "clip_bundle"'
        in result["clip-bundle-v1"].with_suffix(".zip.asset.json").read_text()
    )


def test_asset_pins_are_read_from_shared_spec():
    from maipai_body.link.assets import SPEC_ASSETS_PATH, load_spec_assets

    assets = load_spec_assets(SPEC_ASSETS_PATH)
    assert {asset.id for asset in assets} >= {
        "openwakeword-melspectrogram-v0_5_1",
        "openwakeword-embedding-v0_5_1",
        "hey-maipai-v2",
        "sface-2021dec",
        "yunet-2026may",
        "sherpa-kws-zipformer-gigaspeech-3_3m",
    }
    assert all(len(asset.sha256) == 64 and asset.licence for asset in assets)


def test_base_spec_assets_exclude_optional_moves():
    from maipai_body.link.assets import SPEC_ASSETS_PATH

    assert "moves" not in SPEC_ASSETS_PATH.read_text().lower()


def test_code_has_no_direct_external_asset_urls():
    package = Path(__file__).parents[1] / "maipai_body"
    governed = (
        package / "model_assets.py",
        package / "speech/models.py",
        package / "speech/kws.py",
        package / "speech/offline_clips.py",
        package / "vision/models.py",
        package / "moves/library.py",
    )
    offenders = []
    for path in governed:
        text = path.read_text()
        if "http://" in text or "https://" in text:
            offenders.append(str(path.relative_to(package)))
    assert offenders == []


def test_yunet_cache_is_used_offline(monkeypatch, tmp_path):
    from maipai_body.link.assets import prepare_yunet_cache
    from maipai_body.vision.detect import FiveLandmarkDetector

    model = tmp_path / "face_detection_yunet_2026may.onnx"
    model.write_bytes(b"model")
    prepare_yunet_cache(model, tmp_path / "hf")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    import reachy_mini.vision.face_detector as detector_module

    class FakeSession:
        def __init__(self, *args, **kwargs):
            self.get_inputs = lambda: [type("Item", (), {"name": "input"})()]
            self.get_outputs = lambda: [type("Item", (), {"name": "output"})()]

    monkeypatch.setattr(detector_module, "hf_hub_download", lambda *a, **k: str(model))
    monkeypatch.setattr(detector_module.ort, "InferenceSession", FakeSession)
    detector = FiveLandmarkDetector()
    assert detector is not None


def test_yunet_without_prefilled_cache_has_clear_error(monkeypatch, tmp_path):
    import reachy_mini.vision.face_detector as detector_module
    from huggingface_hub.errors import LocalEntryNotFoundError

    from maipai_body.vision.detect import FiveLandmarkDetector

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setattr(
        detector_module,
        "hf_hub_download",
        lambda *a, **k: (_ for _ in ()).throw(LocalEntryNotFoundError("offline cache miss")),
    )
    with pytest.raises(RuntimeError, match="hub asset sync"):
        FiveLandmarkDetector()
