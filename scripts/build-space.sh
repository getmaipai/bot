#!/usr/bin/env bash
# Assembles the Hugging Face Space layout for the MaiPai Bot listing into
# dist/space/, from a release wheel. Never pushes anywhere: publishing the
# Space by hand, from this directory, is the owner's call (design record
# open question 1).
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/build-space.sh <wheel-path> <version>

  <wheel-path>  Path to the release wheel (dist/*.whl).
  <version>     The release version this Space describes (e.g. 0.1.0).
USAGE
}

if [ "$#" -ne 2 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  usage >&2
  exit 1
fi

WHEEL_PATH="$1"
VERSION="$2"

if [ ! -f "$WHEEL_PATH" ]; then
  echo "error: wheel not found at $WHEEL_PATH" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPACE_DIR="$REPO_ROOT/dist/space"
WHEEL_NAME="$(basename "$WHEEL_PATH")"

rm -rf "$SPACE_DIR"
mkdir -p "$SPACE_DIR"

cp "$WHEEL_PATH" "$SPACE_DIR/$WHEEL_NAME"
cp "$REPO_ROOT/LICENSE" "$SPACE_DIR/LICENSE"

cat >"$SPACE_DIR/README.md" <<EOF
---
title: MaiPai Bot
license: agpl-3.0
tags:
  - reachy_mini_python_app
---

# MaiPai Bot

The robot companion, running as Reachy Mini's own app. Version ${VERSION}.

Install the attached wheel (\`$WHEEL_NAME\`) through the daemon's app
store, or offline over SSH with \`scripts/install-reachy.sh\`.
EOF

echo "== space assembled at $SPACE_DIR (not pushed)"
