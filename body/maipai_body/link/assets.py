"""Authenticated asset synchronization from the paired Home hub."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from maipai_body.model_assets import AssetUnavailable, PinnedAsset, configure_asset_fetcher

_SPEC_ROOT = os.environ.get("MAIPAI_SPEC_DIR")
_PACKAGED_SPEC_ASSETS = Path(__file__).resolve().parent.parent / "robot-assets.json"
_SPEC_CANDIDATES = (
    Path(__file__).resolve().parents[3].parent
    / "commons-tags"
    / "spec-spec-v0.1.76"
    / "spec"
    / "assets"
    / "robot-assets.json",
    _PACKAGED_SPEC_ASSETS,
)
SPEC_ASSETS_PATH = (
    Path(_SPEC_ROOT) / "assets" / "robot-assets.json"
    if _SPEC_ROOT
    else next((path for path in _SPEC_CANDIDATES if path.is_file()), _PACKAGED_SPEC_ASSETS)
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHUNK_BYTES = 1 << 16


class AssetSyncError(RuntimeError):
    """The hub manifest or an asset could not be verified and installed."""


@dataclass(frozen=True)
class SpecAsset:
    id: str
    file: str
    sha256: str
    bytes: int
    licence: str
    source_url: str
    kind: str


def load_spec_assets(path: Path = SPEC_ASSETS_PATH) -> tuple[SpecAsset, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        assets = tuple(SpecAsset(**entry) for entry in raw)
    except (OSError, TypeError, ValueError) as exc:
        raise AssetSyncError(f"cannot read shared robot asset pins at {path}: {exc}") from exc
    if any(not _SHA256.fullmatch(a.sha256) or not a.licence for a in assets):
        raise AssetSyncError("shared robot asset pins require a sha256 and licence")
    if len({a.id for a in assets}) != len(assets):
        raise AssetSyncError("shared robot asset pins contain duplicate ids")
    return assets


def pinned_asset(asset_id: str, *, unavailable_hint: str = "") -> PinnedAsset:
    """Build a consumer pin from the shared spec, never from a local copy."""
    for asset in load_spec_assets():
        if asset.id == asset_id:
            return PinnedAsset(asset.id, asset.file, asset.sha256, unavailable_hint)
    raise AssetSyncError(f"asset {asset_id} is missing from the shared robot asset pins")


class AssetSync:
    """Fetch spec-pinned bytes through the device-authenticated hub API."""

    def __init__(
        self,
        base_url: str,
        session_cookie: str,
        *,
        session: requests.Session | None = None,
        spec_path: Path = SPEC_ASSETS_PATH,
    ) -> None:
        if urlparse(base_url).scheme not in {"http", "https"}:
            raise ValueError("hub URL must use HTTP or HTTPS")
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session_cookie = session_cookie
        self.spec = {asset.id: asset for asset in load_spec_assets(spec_path)}
        self.manifest: dict[str, dict] | None = None

    def _headers(self) -> dict[str, str]:
        return {"Cookie": self.session_cookie}

    def _load_manifest(self) -> dict[str, dict]:
        try:
            response = self.session.get(
                f"{self.base_url}/api/devices/me/assets", headers=self._headers(), timeout=30
            )
            response.raise_for_status()
            entries = response.json()["assets"]
            manifest = {entry["id"]: entry for entry in entries}
            if len(manifest) != len(entries):
                raise ValueError("hub asset manifest contains duplicate ids")
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise AssetSyncError(f"could not read the hub asset manifest: {exc}") from exc
        self.manifest = manifest
        return manifest

    def _entry(self, asset_id: str) -> dict:
        manifest = self.manifest if self.manifest is not None else self._load_manifest()
        entry = manifest.get(asset_id)
        pin = self.spec.get(asset_id)
        if entry is None or pin is None:
            raise AssetUnavailable(f"asset {asset_id} is not pinned and available on the hub")
        if (
            entry.get("sha256") != pin.sha256
            or entry.get("file") != pin.file
            or entry.get("bytes") != pin.bytes
            or entry.get("kind") != pin.kind
        ):
            raise AssetSyncError(f"hub manifest does not match shared pin {asset_id}")
        if not entry.get("available", True):
            raise AssetUnavailable(f"hub asset {asset_id} is not ready")
        if entry.get("kind") == "moves":
            raise AssetUnavailable("optional move assets are installed with their package only")
        return entry

    def _download(self, asset_id: str, cache_dir: Path, filename: str) -> Path:
        self._entry(asset_id)
        pin = self.spec[asset_id]
        if filename != pin.file or Path(filename).name != filename or filename.startswith("."):
            raise AssetSyncError(f"unsafe asset filename for {asset_id}")
        if not _SHA256.fullmatch(pin.sha256):
            raise AssetSyncError(f"invalid sha256 pin for {asset_id}")
        cache_dir.mkdir(parents=True, exist_ok=True)
        dest = cache_dir / filename
        if dest.is_file() and self._sha256(dest) == pin.sha256:
            return dest
        dest.unlink(missing_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        try:
            with self.session.get(
                f"{self.base_url}/api/devices/me/assets/{asset_id}",
                headers=self._headers(),
                stream=True,
                timeout=60,
            ) as response:
                response.raise_for_status()
                with part.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=_CHUNK_BYTES):
                        if chunk:
                            output.write(chunk)
        except requests.RequestException as exc:
            part.unlink(missing_ok=True)
            raise AssetSyncError(f"could not fetch hub asset {asset_id}: {exc}") from exc
        if part.stat().st_size != pin.bytes:
            part.unlink(missing_ok=True)
            raise AssetSyncError(f"hub asset {asset_id} byte count mismatch")
        actual = self._sha256(part)
        if actual != pin.sha256:
            part.unlink(missing_ok=True)
            raise AssetSyncError(f"hub asset {asset_id} checksum mismatch")
        part.replace(dest)
        return dest

    def _download_manifest_asset(self, entry: dict, cache_dir: Path) -> Path:
        """Install device-specific clip or optional move assets from Home."""
        asset_id = entry.get("id")
        filename = entry.get("file")
        digest = entry.get("sha256")
        size = entry.get("bytes")
        kind = entry.get("kind")
        if (
            not isinstance(asset_id, str)
            or not isinstance(filename, str)
            or Path(filename).name != filename
            or filename.startswith(".")
            or not isinstance(digest, str)
            or not _SHA256.fullmatch(digest)
            or not isinstance(size, int)
            or size < 0
            or not entry.get("licence")
            or kind not in {"clip_bundle", "moves"}
            or not entry.get("available")
        ):
            raise AssetSyncError("hub returned an invalid optional asset manifest entry")
        dest = cache_dir / filename
        cache_dir.mkdir(parents=True, exist_ok=True)
        if not (dest.is_file() and dest.stat().st_size == size and self._sha256(dest) == digest):
            dest.unlink(missing_ok=True)
            part = dest.with_suffix(dest.suffix + ".part")
            try:
                with self.session.get(
                    f"{self.base_url}/api/devices/me/assets/{asset_id}",
                    headers=self._headers(),
                    stream=True,
                    timeout=60,
                ) as response:
                    response.raise_for_status()
                    with part.open("wb") as output:
                        for chunk in response.iter_content(chunk_size=_CHUNK_BYTES):
                            if chunk:
                                output.write(chunk)
            except requests.RequestException as exc:
                part.unlink(missing_ok=True)
                raise AssetSyncError(f"could not fetch hub asset {asset_id}: {exc}") from exc
            if part.stat().st_size != size or self._sha256(part) != digest:
                part.unlink(missing_ok=True)
                raise AssetSyncError(f"hub asset {asset_id} size or checksum mismatch")
            part.replace(dest)
        sidecar = dest.with_suffix(dest.suffix + ".asset.json")
        sidecar_part = sidecar.with_suffix(sidecar.suffix + ".part")
        sidecar_part.write_text(
            json.dumps({"id": asset_id, "sha256": digest, "bytes": size, "kind": kind}),
            encoding="utf-8",
        )
        sidecar_part.replace(sidecar)
        return dest

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(_CHUNK_BYTES), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def ensure(self, asset: PinnedAsset, cache_dir: Path) -> Path:
        pin = self.spec.get(asset.id)
        if pin is None or pin.file != asset.file or pin.sha256 != asset.sha256:
            raise AssetSyncError(f"asset {asset.id} differs from the shared spec pin")
        path = cache_dir / asset.file
        if path.is_file() and self._sha256(path) == asset.sha256:
            result = path
        else:
            result = self._download(asset.id, cache_dir, asset.file)
        if asset.id == "yunet-2026may":
            prepare_yunet_cache(result)
        return result

    def sync(self, cache_dir: Path) -> dict[str, Path]:
        """Pull all present base pins, excluding separately installed moves."""
        manifest = self._load_manifest()
        synced: dict[str, Path] = {}
        for asset in self.spec.values():
            entry = manifest.get(asset.id)
            if entry is None or not entry.get("available", True) or entry.get("kind") == "moves":
                continue
            local = PinnedAsset(asset.id, asset.file, asset.sha256)
            synced[asset.id] = self.ensure(local, cache_dir)
        for entry in manifest.values():
            if entry.get("id") not in self.spec and entry.get("kind") in {"clip_bundle", "moves"}:
                if entry.get("available"):
                    synced[entry["id"]] = self._download_manifest_asset(entry, cache_dir)
        configure_asset_fetcher(self.ensure)
        return synced

    def on_asset_changed(self, cache_dir: Path) -> dict[str, Path]:
        """Refresh the manifest and cache after the command channel signals a change."""
        self.manifest = None
        return self.sync(cache_dir)


def prepare_yunet_cache(model_path: Path | None, hf_home: Path | None = None) -> Path:
    """Expose the verified hub file in the exact cache key used by Reachy's SDK."""
    if model_path is None or not model_path.is_file():
        raise RuntimeError("YuNet is missing; run a paired hub asset sync first")
    if hf_home is not None:
        hf_root = hf_home
    elif os.environ.get("HF_HOME"):
        hf_root = Path(os.environ["HF_HOME"])
    else:
        from huggingface_hub.constants import HF_HOME

        hf_root = Path(HF_HOME)
    repo = hf_root / "hub" / "models--pollen-robotics--face_detection_yunet_2026may"
    revision = "2b8e922362946a0db67e861bae0f77826980effd"
    blob = repo / "blobs" / hashlib.sha256(model_path.read_bytes()).hexdigest()
    snapshot = repo / "snapshots" / revision
    blob.parent.mkdir(parents=True, exist_ok=True)
    snapshot.mkdir(parents=True, exist_ok=True)
    if not blob.exists():
        try:
            blob.symlink_to(model_path.resolve())
        except OSError:
            import shutil

            shutil.copyfile(model_path, blob)
    target = snapshot / "face_detection_yunet_2026may.onnx"
    if not target.exists():
        target.symlink_to(Path("../../blobs") / blob.name)
    refs = repo / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(revision, encoding="utf-8")
    os.environ["HF_HOME"] = str(hf_root)
    os.environ["HF_HUB_OFFLINE"] = "1"
    return target
