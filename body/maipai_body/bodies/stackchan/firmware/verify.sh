#!/usr/bin/env bash
set -euo pipefail
DIR=${1:-.}
SUMS="$DIR/SHA256SUMS"
[[ -f "$SUMS" ]] || { echo "Missing SHA256SUMS in $DIR" >&2; exit 1; }
[[ -f "$DIR/flash-manifest.json" ]] || { echo "Missing flash-manifest.json in $DIR: rebuild the release with release.sh --signing-key." >&2; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then (cd "$DIR" && sha256sum -c SHA256SUMS)
else (cd "$DIR" && shasum -a 256 -c SHA256SUMS); fi
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(git -C "$HERE" rev-parse --show-toplevel)
DIR=$(cd "$DIR" && pwd)
cd "$ROOT/body"
MAIPAI_SPEC_DIR="$(bash "$ROOT/scripts/spec-dir.sh")" uv run python - "$DIR/flash-manifest.json" "$DIR" <<'PY'
import hashlib, json, sys
from pathlib import Path
from maipai_body.bodies.stackchan.firmware.flash_manifest import validate_manifest

manifest_path, release_dir = map(Path, sys.argv[1:])
manifest = json.loads(manifest_path.read_text())
try:
    validate_manifest(manifest)
except ValueError as exc:
    raise SystemExit(f"Invalid flash manifest: {exc}")
for build in manifest["builds"]:
    for part in build["parts"]:
        path = release_dir / part["path"]
        if not path.is_file():
            raise SystemExit(f"Missing manifest part {part['path']}")
        data = path.read_bytes()
        if len(data) != part["size"]:
            raise SystemExit(f"Wrong size for manifest part {part['path']}")
        if hashlib.sha256(data).hexdigest() != part["sha256"]:
            raise SystemExit(f"Wrong sha256 for manifest part {part['path']}")
PY
