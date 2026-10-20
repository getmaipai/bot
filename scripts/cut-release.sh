#!/usr/bin/env bash
# Stage and sign a complete Bot release. This script never publishes it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/signing-key.sh"

usage() {
  echo "Usage: $0 <tag> --signing-key PATH|keychain:ITEM [--date YYYY-MM-DD]" >&2
  exit 2
}

TAG="${1:-}"
[[ -n "$TAG" ]] || usage
shift
SIGNING_KEY=""
HAS_SIGNING_KEY=0
BUILD_DATE="$(date -u +%F)"
while (($#)); do
  case "$1" in
    --signing-key) (($# >= 2)) || usage; SIGNING_KEY="$2"; HAS_SIGNING_KEY=1; shift 2 ;;
    --date) (($# >= 2)) || usage; BUILD_DATE="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]] || { echo "Invalid release tag '$TAG'; use v<major>.<minor>.<patch> with an optional prerelease suffix." >&2; exit 2; }
[[ "$HAS_SIGNING_KEY" == 1 && -n "$SIGNING_KEY" ]] || { echo "Missing required --signing-key PATH|keychain:ITEM; provide the release signing key and retry." >&2; exit 2; }
[[ "$BUILD_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "Invalid --date '$BUILD_DATE'; use YYYY-MM-DD." >&2; exit 2; }
VERSION="${TAG#v}"
PACKAGE_VERSION="$(sed -n 's/^version = "\([^"]*\)"$/\1/p' body/pyproject.toml | head -1)"
[[ "$VERSION" == "$PACKAGE_VERSION" ]] || { echo "Release tag $TAG does not match body version $PACKAGE_VERSION; use v$PACKAGE_VERSION or update the package version first." >&2; exit 1; }
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Git tree is dirty; the firmware manifest records the recipe commit. Commit or discard all changes, then run cut-release.sh again." >&2
  exit 1
fi

STAGE="$ROOT/dist/bot-release/$TAG-final"
FW_TMP="$(mktemp -d "${TMPDIR:-/tmp}/maipai-firmware-release.XXXXXX")"
NOTES="$ROOT/dist/bot-release/$TAG-notes.md"
PUBLIC_KEY="$ROOT/dist/bot-release/$TAG-release-public.pem"
mkdir -p "$ROOT/dist/bot-release"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cleanup() { rm -rf "$FW_TMP"; signing_key_cleanup; }
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

for platform in darwin-arm64 linux-x64 linux-arm64; do
  MAIPAI_BOT_BUNDLE_OUT_DIR="$STAGE" scripts/build-hub-bundle.sh "$TAG" "$platform"
done

if ! command -v idf.py >/dev/null 2>&1; then
  # ESP-IDF 5.5 set up its Python env with Homebrew Python 3.12 (as recipe.sh does); a newer python3 first on PATH breaks export.sh.
  export PATH="/opt/homebrew/opt/python@3.12/libexec/bin:$PATH"
  IDF_PATH="${IDF_PATH:-$HOME/esp/esp-idf}"
  if [[ ! -f "$IDF_PATH/export.sh" ]]; then
    echo "idf.py is unavailable and ESP-IDF export script was not found at $IDF_PATH/export.sh; install ESP-IDF 5.5.4 there or add idf.py to PATH." >&2
    exit 1
  fi
  # shellcheck disable=SC1090,SC1091
  source "$IDF_PATH/export.sh"
  if ! command -v idf.py >/dev/null 2>&1; then
    echo "Sourced $IDF_PATH/export.sh but idf.py is still unavailable; repair the ESP-IDF 5.5.4 install and retry." >&2
    exit 1
  fi
fi
bash body/maipai_body/bodies/stackchan/firmware/release.sh \
  --date "$BUILD_DATE" --version "$VERSION" --signing-key "$SIGNING_KEY" --output "$FW_TMP"
MAIPAI_BOT_BUNDLE_OUT_DIR="$STAGE" scripts/build-stackchan-firmware-asset.sh "$TAG" "$FW_TMP"
# The wheel is a build input already packed inside each hub bundle; it is not a release asset.
rm -f "$STAGE"/maipai_bot-*.whl "$STAGE"/maipai_bot-*.whl.sha256
scripts/sign-release-sums.sh --signing-key "$SIGNING_KEY" "$STAGE"

(cd "$STAGE" && shasum -a 256 -c SHA256SUMS)
python3 - "$STAGE" <<'PY'
import pathlib, sys
stage = pathlib.Path(sys.argv[1])
listed = set()
for line in (stage / "SHA256SUMS").read_text().splitlines():
    fields = line.split(None, 1)
    if len(fields) == 2:
        listed.add(fields[1].lstrip("*"))
required = {p.name for p in stage.iterdir() if p.is_file() and p.name not in {"SHA256SUMS", "SHA256SUMS.sig.json"}}
missing = sorted(required - listed)
if missing:
    raise SystemExit("Assets missing from SHA256SUMS: " + ", ".join(missing))
PY

resolve_signing_key "$SIGNING_KEY"
# resolve_signing_key installs its own traps; put back ours so the firmware temp directory is removed too.
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM
mkdir -p "$(dirname "$PUBLIC_KEY")"
openssl pkey -in "$SIGNING_KEY_PATH" -pubout -out "$PUBLIC_KEY"
KEYID="$(openssl pkey -in "$SIGNING_KEY_PATH" -pubout -outform DER | python3 -c 'import hashlib,sys; sys.stdout.write(hashlib.sha256(sys.stdin.buffer.read()[-32:]).hexdigest()[:16])')"

python3 - "$ROOT/CHANGELOG.md" "$VERSION" "$NOTES" <<'PY'
import pathlib, re, sys
source, version, output = map(pathlib.Path, sys.argv[1:])
text = source.read_text()
match = re.search(rf"^## \[{re.escape(str(version))}\] - [^\n]+\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
if not match:
    raise SystemExit(f"CHANGELOG.md has no section for {version}")
output.write_text(f"# MaiPai Bot {version}\n\n" + match.group(1).strip() + "\n")
PY

echo "Public key ($PUBLIC_KEY), keyid $KEYID:"
cat "$PUBLIC_KEY"
echo "Release assets (size, sha256):"
while IFS= read -r line; do
  file="${line#*  }"; file="${file#\*}"
  [[ -f "$STAGE/$file" ]] || continue
  printf '%s %s %s\n' "$(wc -c < "$STAGE/$file" | tr -d ' ')" "$line" "$file"
done < "$STAGE/SHA256SUMS"
echo "Publish command (run manually):"
printf 'gh release create %s --repo getmaipai/bot --title "MaiPai Bot %s" --notes-file %s %s/*\n' "$TAG" "$TAG" "$NOTES" "$STAGE"
