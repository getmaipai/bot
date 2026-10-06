#!/usr/bin/env bash
# Build and stage the wheel and its checksum for an owner-created Bot release.
# This script never creates, pushes, or uploads a release.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <release-tag>" >&2
  exit 2
fi
TAG="$1"
if [[ ! "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
  echo "invalid release tag: $TAG" >&2
  exit 2
fi
VERSION="${TAG#v}"
PACKAGE_VERSION="$(sed -n 's/^version = "\([^"]*\)"$/\1/p' body/pyproject.toml | head -1)"
if [ "$VERSION" != "$PACKAGE_VERSION" ]; then
  echo "release tag $TAG does not match body version $PACKAGE_VERSION" >&2
  exit 1
fi

STAGE="dist/bot-release/$TAG"
rm -rf "$STAGE"
mkdir -p "$STAGE"
(cd body && uv build --wheel --out-dir "../$STAGE")
WHEEL="$STAGE/maipai_bot-$VERSION-py3-none-any.whl"
if [ ! -f "$WHEEL" ]; then
  echo "expected pure Python wheel not found: $WHEEL" >&2
  exit 1
fi
DIST_INFO_VERSION="$(python3 - "$WHEEL" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as wheel:
    metadata_path = next(name for name in wheel.namelist() if name.endswith(".dist-info/METADATA"))
    metadata = wheel.read(metadata_path).decode()
print(next(line.partition(": ")[2] for line in metadata.splitlines() if line.startswith("Version: ")))
PY
)"
if [ "$DIST_INFO_VERSION" != "$VERSION" ]; then
  echo "wheel metadata version $DIST_INFO_VERSION does not match release version $VERSION" >&2
  exit 1
fi
(cd "$STAGE" && shasum -a 256 "$(basename "$WHEEL")" > "$(basename "$WHEEL").sha256")
ASSETS=("$WHEEL" "$WHEEL.sha256")
if [ "${MAIPAI_SKIP_WHEELHOUSE:-0}" != 1 ]; then
  scripts/build-wheelhouse.sh "$VERSION" "$STAGE"
  ASSETS+=("$STAGE/maipai_bot-$VERSION-wheelhouse-aarch64-cp312.tar" "$STAGE/maipai_bot-$VERSION-wheelhouse-aarch64-cp312.tar.sha256")
fi
echo "Staged release assets in $STAGE:"
ls -1 "${ASSETS[@]}"
echo "No release was pushed or uploaded. Attach these $((${#ASSETS[@]})) files to $TAG when the owner publishes it."
