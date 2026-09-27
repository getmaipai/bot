#!/usr/bin/env bash
# Assemble the Hugging Face Space layout for MaiPai Bot's store listing.
#
# Usage: scripts/build-space.sh [version]
#   version   the release tag this build is for (defaults to the
#             nearest git tag, or "0.0.0-dev" if none exists yet)
#
# Run against a tagged checkout at release time (the release skill's
# job); builds body/'s wheel with uv, writes a Space README with the
# reachy_mini_python_app front matter, and copies the wheel and LICENSE
# into dist/space/. Never pushes to Hugging Face: publishing is the
# owner's call (docs/dev/design-reachy-mini-2026-09-27.md section 10,
# open question 1).
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:-$(git describe --tags --abbrev=0 2>/dev/null || echo "0.0.0-dev")}"
DIST_DIR="dist/space"

rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

echo "== building the wheel"
(cd body && uv build --wheel --out-dir "../$DIST_DIR")

WHEEL_FILE="$(ls "$DIST_DIR"/*.whl | head -1)"
WHEEL_NAME="$(basename "$WHEEL_FILE")"

echo "== writing the Space README"
cat >"$DIST_DIR/README.md" <<SPACE_README
---
title: MaiPai Bot
emoji: 🤖
sdk: static
tags:
  - reachy_mini
  - reachy_mini_python_app
license: agpl-3.0
---

# MaiPai Bot

The robot companion, running as a Reachy Mini app: a full replica of
your MaiPai Home household, using the hub as its brain when reachable.
Private, local AI that's actually yours; nothing leaves the robot but
what the privacy page lists.

Install offline over SSH with \`scripts/install-reachy.sh\`, or from
this listing through the robot's own app store once Home's Devices
page walks you through pairing (docs/dev/design-reachy-mini-2026-09-27.md
section 10).

Version: $VERSION
SPACE_README

cp LICENSE "$DIST_DIR/LICENSE"
# uv build's --out-dir already placed the wheel in $DIST_DIR; nothing more to copy.

echo "== done: $DIST_DIR ($WHEEL_NAME, README.md, LICENSE)"
echo "Not pushed anywhere. Publishing to Hugging Face is the owner's call."
