#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$#" -ne 2 ]; then
  echo "usage: $0 <release-tag> <firmware-release-dir>" >&2
  exit 2
fi
TAG="$1"
RELEASE_DIR="$2"
if [[ ! "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
  echo "invalid release tag '$TAG'; use v<major>.<minor>.<patch> with an optional prerelease suffix" >&2
  exit 2
fi
VERSION="${TAG#v}"
if [[ "$RELEASE_DIR" != /* ]]; then
  RELEASE_DIR="$ROOT/$RELEASE_DIR"
fi
DIST_STAGE="$ROOT/dist/bot-release/$TAG"
STAGE="${MAIPAI_BOT_BUNDLE_OUT_DIR:-$DIST_STAGE}"
if [[ "$STAGE" != /* ]]; then
  STAGE="$ROOT/$STAGE"
fi
mkdir -p "$STAGE"
ARCHIVE="$STAGE/stackchan-firmware-$VERSION.tar.gz"

python3 - "$RELEASE_DIR" "$VERSION" "$ARCHIVE" <<'PY'
import gzip
import hashlib
import json
import os
import pathlib
import sys
import tarfile

release = pathlib.Path(sys.argv[1])
version = sys.argv[2]
archive = pathlib.Path(sys.argv[3])
manifest_path = release / "flash-manifest.json"

def refuse(message):
    print(f"{message}; rebuild with release.sh --version {version}", file=sys.stderr)
    raise SystemExit(1)

try:
    manifest = json.loads(manifest_path.read_text())
except (OSError, json.JSONDecodeError) as exc:
    refuse(f"cannot read flash-manifest.json: {exc}")
if "version" in manifest and manifest["version"] != version:
    refuse(f"manifest version {manifest['version']!r} does not match {version}")
try:
    builds = manifest["builds"]
    parts = [part for build in builds for part in build["parts"]]
except (KeyError, TypeError) as exc:
    refuse(f"manifest builds[].parts is invalid: {exc}")

files = [("flash-manifest.json", manifest_path)]
for part in parts:
    name = part.get("path") if isinstance(part, dict) else None
    if (not isinstance(name, str) or not name or name in (".", "..")
            or pathlib.PurePosixPath(name).is_absolute() or pathlib.PureWindowsPath(name).is_absolute()
            or "/" in name or "\\" in name):
        refuse(f"manifest part has unsafe path {name!r}")
    path = release / name
    if not path.is_file():
        refuse(f"manifest part {name!r} is missing")
    data = path.read_bytes()
    if len(data) != part.get("size"):
        refuse(f"manifest part {name!r} size mismatch (expected {part.get('size')}, got {len(data)})")
    digest = hashlib.sha256(data).hexdigest()
    if digest != part.get("sha256"):
        refuse(f"manifest part {name!r} sha256 mismatch")
    files.append((name, path))

with archive.open("wb") as raw:
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w|", format=tarfile.USTAR_FORMAT) as tar:
            for name, path in files:
                info = tarfile.TarInfo(name)
                info.size = path.stat().st_size
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                with path.open("rb") as source:
                    tar.addfile(info, source)
PY

SUMS="$STAGE/SHA256SUMS"
if [ -f "$SUMS" ]; then
  awk -v name="$(basename "$ARCHIVE")" '$2 != name && $2 != "*" name { print }' "$SUMS" > "$SUMS.tmp"
  mv "$SUMS.tmp" "$SUMS"
fi
(cd "$STAGE" && shasum -a 256 "$(basename "$ARCHIVE")" >> SHA256SUMS)
echo "Built $ARCHIVE"
echo "Reminder: sign the final SHA256SUMS with scripts/sign-release-sums.sh --signing-key keychain:<item> <stage-dir> after all bundles and this asset are staged."
