#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(git -C "$HERE" rev-parse --show-toplevel)
PINS="$HERE/pins.toml"
BUILD_DATE=""
VERSION="1.0.0"
OUT=""
CHECK_PINS=0
SIGNING_KEY=""
CONTAINER="${STACKCHAN_CONTAINER:-docker}"
CONTAINER_IMAGE="espressif/idf:v5.5.4"
while (($#)); do
  case "$1" in
    --date) BUILD_DATE="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --output) OUT="$2"; shift 2 ;;
    --pins) PINS="$2"; shift 2 ;;
    --signing-key) SIGNING_KEY="$2"; shift 2 ;;
    --container-image) CONTAINER_IMAGE="$2"; shift 2 ;;
    --check-pins) CHECK_PINS=1; shift ;;
    *) echo "Usage: release.sh --date YYYY-MM-DD --signing-key PATH|keychain:ITEM [--output DIR] [--pins FILE]" >&2; exit 2 ;;
  esac
done
if [[ "$CHECK_PINS" != "1" ]]; then
  [[ -n "$SIGNING_KEY" ]] || { echo "Pass --signing-key PATH to sign the flash manifest." >&2; exit 2; }
fi
USE_CONTAINER=0
if command -v "$CONTAINER" >/dev/null 2>&1; then USE_CONTAINER=1; fi
python3 - "$PINS" "$USE_CONTAINER" <<'PY'
import re, sys, tomllib
from pathlib import Path
p = tomllib.loads(Path(sys.argv[1]).read_text())
use_container = sys.argv[2] == "1"
missing = []
checks = [("stackchan", "repos_json_sha256")] + [("stackchan", "dependencies_lock_sha256")]
# The container image is pinned by digest only when the build runs in it; the local toolchain is checked by version in recipe.sh.
if use_container:
    checks.append(("toolchain", "container_sha256"))
for section, key in checks:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(p.get(section, {}).get(key, ""))):
        missing.append(f"{section}.{key}")
# Git dependencies are content-addressed by their full commit, which recipe.sh checks after checkout.
for section, row in [("stackchan", p.get("stackchan", {}))] + [(f"dependencies.{n}", r) for n, r in p.get("dependencies", {}).items()]:
    if not re.fullmatch(r"[0-9a-f]{40}", str(row.get("commit", ""))):
        missing.append(f"{section}.commit")
if missing:
    raise SystemExit("Missing or invalid pin checksum(s): " + ", ".join(missing) + ". Fill them in pins.toml and run the release again.")
PY
if [[ "$CHECK_PINS" == "1" ]]; then exit 0; fi
source "$ROOT/scripts/signing-key.sh"
resolve_signing_key "$SIGNING_KEY"
[[ -n "$BUILD_DATE" ]] || { echo "Pass --date YYYY-MM-DD for reproducible release metadata." >&2; exit 2; }
if [[ -z "$OUT" ]]; then OUT="$ROOT/dist/stackchan-release-$BUILD_DATE"; fi
mkdir -p "$OUT"
if [[ "$USE_CONTAINER" == "1" ]]; then
  CONTAINER_DIGEST=$(python3 -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["toolchain"]["container_sha256"])' "$PINS")
  "$CONTAINER" run --rm -e MAIPAI_FIRMWARE_VERSION="$VERSION" -v "$ROOT:/work" -w /work "$CONTAINER_IMAGE@sha256:$CONTAINER_DIGEST" \
    bash body/maipai_body/bodies/stackchan/firmware/recipe.sh
else
  echo "Container engine unavailable; documented local-toolchain fallback: run recipe.sh with ESP-IDF 5.5.4 exported." >&2
  MAIPAI_FIRMWARE_VERSION="$VERSION" bash "$HERE/recipe.sh"
fi
RECIPE_ROOT="${STACKCHAN_BUILD_ROOT:-$HOME/esp/stackchan-build/stackchan-02-run/build}"
RECIPE_OUT="$RECIPE_ROOT/output"
# The ESP-IDF build tree (bootloader, partition table, flasher_args.json) is inside the checkout recipe.sh builds.
BUILD_DIR="$RECIPE_ROOT/StackChan/firmware/build"
cp "$RECIPE_OUT/stack-chan-maipai.bin" "$OUT/"
cp "$RECIPE_OUT/generated_assets.bin" "$RECIPE_OUT/ota_data_initial.bin" "$OUT/"
cp "$BUILD_DIR/bootloader/bootloader.bin" "$BUILD_DIR/partition_table/partition-table.bin" "$OUT/"
strings "$OUT/stack-chan-maipai.bin" > "$OUT/image-strings.txt"
bash "$ROOT/scripts/stackchan-no-third-party.sh" --strings "$OUT/image-strings.txt"
(cd "$ROOT/body" && MAIPAI_SPEC_DIR="$(bash "$ROOT/scripts/spec-dir.sh")" uv run python -m maipai_body.bodies.stackchan.firmware.flash_manifest build \
  --build-dir "$BUILD_DIR" --release-dir "$OUT" --version "$VERSION" \
  --date "$BUILD_DATE" --key "$SIGNING_KEY_PATH" --out "$OUT/flash-manifest.json")
python3 - "$HERE" "$ROOT" "$BUILD_DATE" "$OUT/manifest.json" <<'PY'
import hashlib,json,subprocess,sys,tomllib
from pathlib import Path
here,root,date,out=map(Path,sys.argv[1:])
pins=tomllib.loads((here/'pins.toml').read_text())
patches=sorted((here/'patches').glob('*.patch'))
payload={"recipe_commit":subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),"pins":pins,"patches":[{"path":str(p.relative_to(here)),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in patches],"esp_idf_version":pins['toolchain']['esp_idf'],"build_date":date.name}
out.write_text(json.dumps(payload,sort_keys=True,indent=2)+'\n')
PY
(cd "$OUT" && shasum -a 256 stack-chan-maipai.bin generated_assets.bin ota_data_initial.bin bootloader.bin partition-table.bin flash-manifest.json manifest.json image-strings.txt > SHA256SUMS)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/maipai-release-public.XXXXXX")
chmod 700 "$TMP"
trap 'rm -rf "$TMP"; signing_key_cleanup' EXIT
trap 'rm -rf "$TMP"; signing_key_cleanup; exit 130' INT
trap 'rm -rf "$TMP"; signing_key_cleanup; exit 143' TERM
openssl pkey -in "$SIGNING_KEY_PATH" -pubout -out "$TMP/release-public.pem"
chmod 600 "$TMP/release-public.pem"
"$HERE/verify.sh" --public-key "$TMP/release-public.pem" "$OUT"
