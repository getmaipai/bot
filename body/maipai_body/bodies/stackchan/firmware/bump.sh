#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
if [[ $# -ne 1 ]]; then
  echo "Usage: bump.sh <m5stack/StackChan commit>" >&2
  echo "Pass a commit hash to check whether the pinned patch series still applies." >&2
  exit 2
fi
commit=$1
if [[ ! "$commit" =~ ^[0-9a-fA-F]{7,40}$ ]]; then
  echo "Invalid upstream commit: $commit. Pass a hexadecimal Git commit hash and retry." >&2
  exit 2
fi
WORK="${STACKCHAN_BUMP_ROOT:-$HOME/esp/stackchan-build/stackchan-bump-$commit}"
rm -rf "$WORK"
mkdir -p "$WORK"
git clone https://github.com/m5stack/StackChan.git "$WORK/StackChan"
git -C "$WORK/StackChan" checkout --detach "$commit"
FW="$WORK/StackChan/firmware"
python3 - "$FW" <<'PY'
import json, subprocess, sys
from pathlib import Path
fw=Path(sys.argv[1])
for row in json.loads((fw/'repos.json').read_text()):
 path=fw/row['path']
 subprocess.run(['git','clone',row['url'],str(path)],check=True)
 subprocess.run(['git','-C',str(path),'checkout','--detach',row['branch']],check=True)
 if row.get('patch'):
  patch=fw/row['patch']
  subprocess.run(['git','-C',str(path),'apply','--check',str(patch)],check=True)
  subprocess.run(['git','-C',str(path),'apply',str(patch)],check=True)
  print('M5-PATCH-OK:',row['patch'])
PY
apply_patch() {
  local patch_file=$1 target=$2 temp="$WORK/patch.tmp"
  sed -n '/^diff --git/,$p' "$HERE/patches/$patch_file" > "$temp"
  if ! git -C "$target" apply --unidiff-zero --check "$temp"; then
    echo "PATCH-FAIL: $patch_file" >&2
    return 1
  fi
  git -C "$target" apply --unidiff-zero "$temp"
  echo "PATCH-OK: $patch_file"
}
failed=0
for item in '001-server-url-empty.patch:root' '002-nvs-websocket-no-ota.patch:xiaozhi-esp32' '004-configurable-sntp-empty.patch:root' '005-disable-m5-registry-mqtt.patch:root' '007-unique-firmware-identity.patch:root'; do
  name=${item%%:*}; target=${item##*:}
  if [[ "$target" == root ]]; then target=$FW; else target=$FW/$target; fi
  apply_patch "$name" "$WORK/StackChan" || failed=1
done
if [[ $failed -ne 0 ]]; then
  echo "BUMP-STOP: one or more MaiPai patches no longer apply. Review failed patch contexts before updating pins." >&2
  exit 1
fi
echo "PATCH-SERIES-OK: upstream $commit"
