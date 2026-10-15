#!/usr/bin/env bash
# MaiPai Bot pre-commit gate. Own checks land here as the robot is built;
# for now this only runs the pinned @maipai/standards core. With --docs it
# runs only the standards core. With --pre (tier T1, `scripts/wt.sh check`) it
# runs ruff, the runtime typecheck and the standards core; the tests beside
# the changed files run from scripts/wt-tests.sh, and the full gate (no flag)
# stays the T2 gate.
set -euo pipefail
cd "$(dirname "$0")/.."

DOCS_ONLY=0; PRE_ONLY=0
case "${1:-}" in
  --docs) DOCS_ONLY=1 ;;
  --pre) PRE_ONLY=1 ;;
  "") ;;
  *) echo "unknown option '$1'; use --docs (standards core only), --pre (cheap preflight) or no flag (full gate)."; exit 2 ;;
esac

if [ "$DOCS_ONLY" = 1 ]; then
  echo "== scope: docs (explicit --docs scope)"
elif [ "$PRE_ONLY" = 1 ]; then
  echo "== scope: pre (ruff, runtime typecheck and standards core)"
else
  echo "== scope: full (body/runtime repository checks and standards core)"
fi

if [ "$DOCS_ONLY" = 0 ] && [ -d body ]; then
  SPEC_DIR="$(bash scripts/spec-dir.sh)"
  echo "== body: ruff"
  (cd body && uv run ruff check . && uv run ruff format --check .)

  if [ "$PRE_ONLY" = 0 ]; then
    echo "== body: pytest"
    (cd body && MAIPAI_SPEC_DIR="$SPEC_DIR" uv run --extra voice pytest -q)
  fi
fi

if [ "$DOCS_ONLY" = 0 ] && [ -d runtime ]; then
  echo "== runtime: install"
  (cd runtime && bun install --silent)

  echo "== runtime: typecheck"
  (cd runtime && bunx tsc --noEmit)

  if [ "$PRE_ONLY" = 0 ]; then
    echo "== runtime: tests"
    (cd runtime && bun test)
  fi
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
