#!/usr/bin/env bash
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$repo_root/data-scratch"
log_file="$(mktemp "$repo_root/data-scratch/gate-report.XXXXXX")"
trap 'rm -f "$log_file"' EXIT

bash "$repo_root/scripts/check.sh" "$@" 2>&1 | tee "$log_file"
check_exit=${PIPESTATUS[0]}
scope_line="$(awk '/^== scope:/ { print; exit }' "$log_file")"
if [[ -n "$scope_line" ]]; then
    printf '%s\n' "$scope_line"
else
    printf 'SCOPE_LINE:NOT_FOUND\n'
fi
printf 'CHECK_EXIT:%d\n' "$check_exit"
exit "$check_exit"
