#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PIN_FILE="$HERE/pins.toml"
BUILD_ROOT="${STACKCHAN_BUILD_ROOT:-$HOME/esp/stackchan-build/stackchan-02-run/build}"
SRC="$BUILD_ROOT/StackChan"
OUT="$BUILD_ROOT/output"

export PATH="/opt/homebrew/opt/python@3.12/libexec/bin:$PATH"
IDF_EXPORT="${IDF_EXPORT:-$HOME/esp/esp-idf/export.sh}"
if [[ ! -f "$IDF_EXPORT" ]]; then
  echo "ESP-IDF export script is missing at $IDF_EXPORT. Install ESP-IDF 5.5.4 and retry." >&2
  exit 2
fi
# shellcheck disable=SC1090
. "$IDF_EXPORT" >/dev/null

read_pin() {
  python3 - "$PIN_FILE" "$1" "$2" <<'PY'
import sys, tomllib
with open(sys.argv[1], 'rb') as f:
    data = tomllib.load(f)
print(data[sys.argv[2]][sys.argv[3]])
PY
}
STACKCHAN_URL=$(read_pin stackchan repository)
STACKCHAN_COMMIT=$(read_pin stackchan commit)
REPOS_HASH=$(read_pin stackchan repos_json_sha256)
mkdir -p "$BUILD_ROOT" "$OUT"
rm -rf "$SRC"
git clone "$STACKCHAN_URL" "$SRC"
git -C "$SRC" checkout --detach "$STACKCHAN_COMMIT"
[[ "$(git -C "$SRC" rev-parse HEAD)" == "$STACKCHAN_COMMIT" ]] || { echo "StackChan checkout does not match pins.toml. Check the repository and retry." >&2; exit 1; }
# GCC substitutes SOURCE_DATE_EPOCH for __DATE__ and __TIME__, making the app descriptor stable.
export SOURCE_DATE_EPOCH="$(git -C "$SRC" show -s --format=%ct "$STACKCHAN_COMMIT")"
FW="$SRC/firmware"
actual_repos_hash=$(shasum -a 256 "$FW/repos.json" | awk '{print $1}')
[[ "$actual_repos_hash" == "$REPOS_HASH" ]] || { echo "repos.json checksum changed from pins.toml. Review dependency pins before building." >&2; exit 1; }

python3 - "$FW" "$PIN_FILE" <<'PY'
import json, subprocess, sys, tomllib
from pathlib import Path
fw = Path(sys.argv[1])
pins = tomllib.loads(Path(sys.argv[2]).read_text())
rows = json.loads((fw / 'repos.json').read_text())
expected = {item['path']: item['commit'] for item in pins['dependencies'].values()}
for item in rows:
    path = fw / item['path']
    ref = item['branch']
    subprocess.run(['git', 'clone', item['url'], str(path)], check=True)
    subprocess.run(['git', '-C', str(path), 'checkout', '--detach', ref], check=True)
    actual = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != expected[item['path']]:
        raise SystemExit(f"Pinned dependency mismatch at {item['path']}: expected {expected[item['path']]}, got {actual}")
    m5_patch = item.get('patch')
    if m5_patch:
        patch = fw / m5_patch
        subprocess.run(['git', '-C', str(path), 'apply', '--check', str(patch)], check=True)
        subprocess.run(['git', '-C', str(path), 'apply', str(patch)], check=True)
        print(f"M5-PATCH-OK: {m5_patch}")
PY

apply_repo_patch() {
  local patch_file=$1 target=$2 temp="$BUILD_ROOT/patch.tmp"
  sed -n '/^diff --git/,$p' "$HERE/patches/$patch_file" > "$temp"
  if ! git -C "$target" apply --unidiff-zero --check "$temp"; then
    echo "Patch failed: $patch_file at $target" >&2
    exit 1
  fi
  git -C "$target" apply --unidiff-zero "$temp"
  echo "PATCH-OK: $patch_file"
}
apply_repo_patch 001-server-url-empty.patch "$SRC"
apply_repo_patch 002-nvs-websocket-no-ota.patch "$SRC"
apply_repo_patch 004-configurable-sntp-empty.patch "$SRC"
apply_repo_patch 005-disable-m5-registry-mqtt.patch "$SRC"
apply_repo_patch 007-unique-firmware-identity.patch "$SRC"

cat > "$FW/sdkconfig.defaults.local" <<'CFG'
CONFIG_STACKCHAN_SERVER_URL=""
CONFIG_OTA_URL=""
CONFIG_STACKCHAN_NTP_SERVER=""
CONFIG_STACKCHAN_XIAOZHI_OTA_CHECK=n
CFG

(cd "$FW" && idf.py fullclean && idf.py build)
echo BUILD-OK
image="$FW/build/maipai-stackchan.bin"
"$HERE/host-search.sh" "$image"
mkdir -p "$OUT"
cp "$image" "$OUT/stack-chan-maipai.bin"
cp "$FW/build/generated_assets.bin" "$OUT/"
cp "$FW/build/ota_data_initial.bin" "$OUT/"
(cd "$OUT" && shasum -a 256 stack-chan-maipai.bin generated_assets.bin ota_data_initial.bin > SHA256SUMS)
cat "$OUT/SHA256SUMS"
