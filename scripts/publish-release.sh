#!/usr/bin/env bash
# One command for a Bot release: key (first time only), GitHub login, cut, one confirmation, publish, Home pin values.
# Usage: scripts/publish-release.sh vX.Y.Z [--date YYYY-MM-DD]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TAG="${1:-}"
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Usage: $0 vX.Y.Z [--date YYYY-MM-DD]" >&2; exit 2; }
shift
DATE_ARGS=("$@")
ITEM="maipai-release-signing-key"
SSL=/opt/homebrew/bin/openssl
[[ -x "$SSL" ]] || { echo "Homebrew OpenSSL is missing; run: brew install openssl" >&2; exit 1; }

if ! security find-generic-password -s "$ITEM" >/dev/null 2>&1; then
  echo "First release on this Mac: creating the signing key in the Keychain item $ITEM."
  KEYDIR="$(mktemp -d)"; chmod 700 "$KEYDIR"
  trap 'rm -rf "$KEYDIR"' EXIT
  "$SSL" genpkey -algorithm ed25519 -out "$KEYDIR/key.pem"
  security add-generic-password -s "$ITEM" -a maipai -w "$(cat "$KEYDIR/key.pem")"
  rm -rf "$KEYDIR"
fi

gh auth status >/dev/null 2>&1 || gh auth login --git-protocol https --web

[[ -z "$(git status --porcelain)" ]] || { echo "The bot checkout has uncommitted changes; commit or discard them, then run again." >&2; exit 1; }
git fetch -q origin main
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || { echo "Local main is not the same as origin/main; push or pull first." >&2; exit 1; }

bash scripts/cut-release.sh "$TAG" --signing-key "keychain:$ITEM" ${DATE_ARGS[@]+"${DATE_ARGS[@]}"}
STAGE="$ROOT/dist/bot-release/$TAG-final"
NOTES="$ROOT/dist/bot-release/$TAG-notes.md"
PUB="$ROOT/dist/bot-release/$TAG-release-public.pem"

echo
echo "Ready to publish $TAG to getmaipai/bot with these assets:"
ls -1 "$STAGE"
read -r -p "Publish now? Type yes: " ANSWER
[[ "$ANSWER" == "yes" ]] || { echo "Not published. Nothing was uploaded; the staged files are in $STAGE."; exit 0; }

gh release create "$TAG" --repo getmaipai/bot --title "MaiPai Bot $TAG" --notes-file "$NOTES" "$STAGE"/*

FW="$STAGE/stackchan-firmware-${TAG#v}.tar.gz"
echo
echo "Published $TAG. Values for Home's firmware.stackchan pin:"
echo "  name:   $(basename "$FW")"
echo "  sha256: $(shasum -a 256 "$FW" | cut -d' ' -f1)"
echo "  size:   $(wc -c < "$FW" | tr -d ' ')"
echo "Public key ($PUB):"
cat "$PUB"
