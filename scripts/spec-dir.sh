#!/usr/bin/env bash
# Prints the absolute path of the pinned @maipai/spec directory (the pin lives in
# body/maipai_body/spec_pin.py); MAIPAI_SPEC_DIR overrides it. Used by check.sh and
# wt-tests.sh so the pin is resolved in one place.
set -euo pipefail
cd "$(dirname "$0")/.."
SPEC_CHECKOUT="$(cd body && uv run python -c 'from maipai_body.spec_pin import SPEC_CHECKOUT; print(SPEC_CHECKOUT)')"
SPEC_DIR="${MAIPAI_SPEC_DIR:-../$SPEC_CHECKOUT}"
if [ ! -f "$SPEC_DIR/vocab/capabilities.json" ]; then
  echo "@maipai/spec $SPEC_CHECKOUT is missing at $SPEC_DIR (set MAIPAI_SPEC_DIR to its spec/ directory)" >&2
  exit 1
fi
cd "$SPEC_DIR" && pwd
