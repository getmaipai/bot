#!/usr/bin/env bash
# T1 test selection for `scripts/wt.sh check`: runs the body tests that changed, sit
# beside a changed module (test_<module>*.py), or mention a changed module's name, and
# the runtime tests when runtime/ changed. Usage: scripts/wt-tests.sh <changed file>...
set -euo pipefail
cd "$(dirname "$0")/.."

tests=()
runtime_changed=0
for f in "$@"; do
  case "$f" in
    body/tests/test_*.py) [ -f "$f" ] && tests+=("${f#body/}") ;;
    body/maipai_body/*.py)
      stem="$(basename "$f" .py)"
      [ "$stem" = "__init__" ] && stem="$(basename "$(dirname "$f")")"
      while IFS= read -r t; do [ -n "$t" ] && tests+=("${t#body/}"); done < <(grep -rlE --include='test_*.py' -e "(^|[^a-z_])$stem([^a-z_]|$)" body/tests 2>/dev/null || true)
      ;;
    runtime/*) runtime_changed=1 ;;
  esac
done

rc=0
if [ "${#tests[@]}" -gt 0 ]; then
  uniq=(); while IFS= read -r t; do uniq+=("$t"); done < <(printf '%s\n' "${tests[@]}" | sort -u)
  echo "== body: pytest (${#uniq[@]} files beside the change)"
  spec_dir="$(bash scripts/spec-dir.sh)"
  (cd body && MAIPAI_SPEC_DIR="$spec_dir" uv run --extra voice pytest -q "${uniq[@]}") || rc=$?
else
  echo "== body: no test files beside the change"
fi
if [ "$runtime_changed" = 1 ] && [ -d runtime ]; then
  echo "== runtime: tests"
  (cd runtime && bun test) || rc=$?
fi
exit "$rc"
