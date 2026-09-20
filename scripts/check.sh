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

STANDARDS_DIR="${MAIPAI_STANDARDS_DIR:-../.github}"
if [ ! -d "$STANDARDS_DIR/standards" ]; then
  echo "missing @maipai/standards checkout at $STANDARDS_DIR (pin std-v0.2.0)"
  exit 1
fi

echo "== standards core (std-v0.2.0)"
bash "$STANDARDS_DIR/standards/bin/check-core.sh" "$(pwd)"

echo "== all checks passed"
