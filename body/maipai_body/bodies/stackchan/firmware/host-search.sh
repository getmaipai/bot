#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "Usage: host-search.sh <firmware-image>" >&2
  echo "Pass the built StackChan binary to scan for vendor endpoints." >&2
  exit 2
fi
image=$1
strings_bin=$(command -v strings || true)
if [[ -z "$strings_bin" ]]; then
  echo "strings was not found. Install the Xcode command line tools, then rerun the host scan." >&2
  exit 2
fi
scratch=$(mktemp)
trap 'rm -f "$scratch"' EXIT
"$strings_bin" "$image" > "$scratch"
blocked=(
  'api.tenclass.net/xiaozhi/ota/'
  '47.113.125.164:12800'
  'ezdata2.m5stack.com'
  'my.m5stack.com/ezdata2'
  'uiflow2.m5stack.com'
  'pool.ntp.org'
  'time.google.com'
  'cn.pool.ntp.org'
  'raw.githubusercontent.com'
)
found=0
for host in "${blocked[@]}"; do
  if grep -Fq -- "$host" "$scratch"; then
    echo "HOST-FOUND: $host"
    found=1
  fi
done
if [[ $found -ne 0 ]]; then
  echo "Host scan failed. Remove these external endpoints or justify each from a captured network trace." >&2
  exit 1
fi
# Text-only reference strings accepted by the baseline inventory. They are not connection targets.
for allowed in 'apps.apple.com' 'play.google.com' 'feishu.cn' '192.168.4.1'; do
  if grep -Fq -- "$allowed" "$scratch"; then
    echo "TEXT-ONLY: $allowed"
  fi
done
echo "HOST-SCAN-OK: $image"
