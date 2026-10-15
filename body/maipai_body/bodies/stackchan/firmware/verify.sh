#!/usr/bin/env bash
set -euo pipefail
DIR=${1:-.}
SUMS="$DIR/SHA256SUMS"
[[ -f "$SUMS" ]] || { echo "Missing SHA256SUMS in $DIR" >&2; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then (cd "$DIR" && sha256sum -c SHA256SUMS)
else (cd "$DIR" && shasum -a 256 -c SHA256SUMS); fi
