#!/usr/bin/env bash
set -euo pipefail
DIR=""
PUBLIC_KEY=""
while (($#)); do
  case "$1" in
    --public-key) (($# >= 2)) || { echo "Pass --public-key PATH (the release's Ed25519 public key PEM) so verify.sh can check the flash manifest signature." >&2; exit 2; }; PUBLIC_KEY="$2"; shift 2 ;;
    *) [[ -z "$DIR" ]] || { echo "Usage: verify.sh [--public-key PATH] DIR" >&2; exit 2; }; DIR="$1"; shift ;;
  esac
done
[[ -n "$PUBLIC_KEY" ]] || { echo "Pass --public-key PATH (the release's Ed25519 public key PEM) so verify.sh can check the flash manifest signature." >&2; exit 2; }
[[ -f "$PUBLIC_KEY" && -r "$PUBLIC_KEY" ]] || { echo "Public key is missing or unreadable: $PUBLIC_KEY; pass the release public key PEM with --public-key PATH." >&2; exit 2; }
DIR=${DIR:-.}
SUMS="$DIR/SHA256SUMS"
[[ -f "$SUMS" ]] || { echo "Missing SHA256SUMS in $DIR" >&2; exit 1; }
[[ -f "$DIR/flash-manifest.json" ]] || { echo "Missing flash-manifest.json in $DIR: rebuild the release with release.sh --signing-key." >&2; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then (cd "$DIR" && sha256sum -c SHA256SUMS)
else (cd "$DIR" && shasum -a 256 -c SHA256SUMS); fi
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(git -C "$HERE" rev-parse --show-toplevel)
DIR=$(cd "$DIR" && pwd)
cd "$ROOT/body"
MAIPAI_SPEC_DIR="$(bash "$ROOT/scripts/spec-dir.sh")" uv run python - "$DIR/flash-manifest.json" "$DIR" "$PUBLIC_KEY" <<'PY'
import hashlib, json, sys
from pathlib import Path
from maipai_body.bodies.stackchan.firmware.flash_manifest import validate_manifest, verify_manifest

manifest_path, release_dir, public_key = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
manifest = json.loads(manifest_path.read_text())
if "signature" not in manifest:
    raise SystemExit("flash-manifest.json is not signed: rebuild the release with release.sh --signing-key.")
try:
    validate_manifest(manifest)
except ValueError as exc:
    raise SystemExit(f"Invalid flash manifest: {exc}")
if not verify_manifest(manifest, public_key):
    raise SystemExit(f"flash-manifest.json signature does not match the public key {public_key}: check you passed the release public key, or rebuild the release with release.sh --signing-key.")
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
