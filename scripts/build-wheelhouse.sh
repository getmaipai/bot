#!/usr/bin/env bash
# Resolve the Bot's pinned runtime for a Reachy Mini CM4 and stage only wheels.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-}"
STAGE="${2:-$ROOT/dist/bot-release/v$VERSION}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
  echo "usage: $0 <version> [release-stage-directory]" >&2
  exit 2
fi
WHEEL="$STAGE/maipai_bot-$VERSION-py3-none-any.whl"
if [ ! -f "$WHEEL" ]; then
  echo "release wheel missing: $WHEEL" >&2
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
REQ="$WORK/requirements-aarch64-cp312.txt"
WHEELS="$WORK/wheels"
mkdir -p "$WHEELS"

# uv applies pyproject.toml's explicit onnxruntime override (1.30.0),
# unlike pip resolving reachy-mini's upstream 1.27.0 pin on its own.
(cd "$ROOT/body" && uv pip compile pyproject.toml \
  --python-platform aarch64-unknown-linux-gnu \
  --extra voice --extra kws --no-header --no-annotate \
  --output-file "$REQ")
grep -qx 'onnxruntime==1.30.0' "$REQ" || {
  echo "resolved requirements do not pin onnxruntime==1.30.0" >&2
  exit 1
}
grep -qi '^sherpa-onnx==' "$REQ" || {
  echo "resolved requirements omit sherpa-onnx" >&2
  exit 1
}

python3 -m pip download \
  --dest "$WHEELS" \
  --platform manylinux2014_aarch64 \
  --python-version 3.12 \
  --implementation cp \
  --abi cp312 \
  --only-binary=:all: \
  --no-deps \
  --requirement "$REQ"
cp "$REQ" "$WHEELS/requirements-aarch64-cp312.txt"
cp "$WHEEL" "$WHEELS/"

shopt -s nullglob
ONNX=("$WHEELS"/onnxruntime-1.30.0-*aarch64*.whl)
SHERPA=("$WHEELS"/sherpa_onnx-*aarch64*.whl "$WHEELS"/sherpa-onnx-*aarch64*.whl)
REACHY=("$WHEELS"/reachy_mini-1.11.0-*.whl)
if [ "${#ONNX[@]}" -ne 1 ] || [ "${#SHERPA[@]}" -lt 1 ] || [ "${#REACHY[@]}" -ne 1 ]; then
  echo "wheelhouse missing aarch64 onnxruntime 1.30.0, sherpa_onnx, or reachy-mini 1.11.0 wheel" >&2
  exit 1
fi
if zipgrep -qi posthog "${REACHY[0]}"; then
  echo "pinned reachy-mini wheel contains posthog; refusing release" >&2
  exit 1
fi

ARCHIVE="$STAGE/maipai_bot-$VERSION-wheelhouse-aarch64-cp312.tar"
tar -cf "$ARCHIVE" -C "$WHEELS" .
(cd "$STAGE" && shasum -a 256 "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256")
tar -tf "$ARCHIVE" | rg -q 'onnxruntime-1\.30\.0-.*aarch64.*\.whl$'
tar -tf "$ARCHIVE" | rg -q 'sherpa[_-]onnx-.*aarch64.*\.whl$'
echo "Staged $(basename "$ARCHIVE") and checksum in $STAGE"
