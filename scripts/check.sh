#!/usr/bin/env bash
# MaiPai Bot pre-commit gate. Own checks land here as the robot is built;
# for now this only runs the pinned @maipai/standards core.
set -euo pipefail
cd "$(dirname "$0")/.."

DOCS_ONLY=0; if [ "${1:-}" = "--docs" ]; then DOCS_ONLY=1; fi

if [ "$DOCS_ONLY" = 0 ] && [ -d body ]; then
  echo "== body: ruff"
  (cd body && uv run ruff check . && uv run ruff format --check .)

  echo "== body: pytest"
  (cd body && uv run pytest -q)
fi

if [ "$DOCS_ONLY" = 0 ] && [ -d runtime ]; then
  echo "== runtime: install"
  (cd runtime && bun install --silent)

  echo "== runtime: typecheck"
  (cd runtime && bunx tsc --noEmit)

  echo "== runtime: tests"
  (cd runtime && bun test)
fi

STANDARDS_REPO="${MAIPAI_STANDARDS_DIR:-../.github}"
STD_TAG="std-v0.3.0"
if [ ! -x "$STANDARDS_REPO/standards/bin/ensure-tag.sh" ]; then
  echo "getmaipai/.github is missing at $STANDARDS_REPO or older than std-v0.3.0 (set MAIPAI_STANDARDS_DIR to a checkout that has standards/bin/ensure-tag.sh)"
  exit 1
fi
STANDARDS_DIR="$(bash "$STANDARDS_REPO/standards/bin/ensure-tag.sh" "$STD_TAG")"
if [ "$(cat "$STANDARDS_DIR/standards/VERSION")" != "${STD_TAG#std-v}" ]; then
  echo "@maipai/standards at $STANDARDS_DIR is $(cat "$STANDARDS_DIR/standards/VERSION"), but the tag is $STD_TAG"
  exit 1
fi

echo "== standards core ($STD_TAG)"
bash "$STANDARDS_DIR/standards/bin/check-core.sh" "$(pwd)"

echo "== all checks passed"
