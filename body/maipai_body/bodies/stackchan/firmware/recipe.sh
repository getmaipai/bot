#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PIN_FILE="$HERE/pins.toml"
export PATH="/opt/homebrew/opt/python@3.12/libexec/bin:$PATH"
CA_FILE=""
AVATAR_SERVER_URL=""
DEVICE_ID=""
CLIENT_ID=""
PAIRING_TOKEN=""
PERSISTENT_WEBSOCKET=""
while (($#)); do
  case "$1" in
    --no-persistent-websocket)
      PERSISTENT_WEBSOCKET=n
      shift
      ;;
    --ca-file)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "--ca-file needs a PEM file path. Retry with --ca-file /path/to/ca.pem." >&2
        exit 2
      fi
      CA_FILE="$2"
      shift 2
      ;;
    --avatar-server-url)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "--avatar-server-url needs a ws:// or wss:// URL. Retry with --avatar-server-url ws://192.0.2.10:8766." >&2
        exit 2
      fi
      AVATAR_SERVER_URL="$2"
      shift 2
      ;;
    --device-id)
      if (($# < 2)) || [[ -z "$2" ]]; then echo "--device-id needs the device MAC address." >&2; exit 2; fi
      DEVICE_ID="$2"; shift 2 ;;
    --client-id)
      if (($# < 2)) || [[ -z "$2" ]]; then echo "--client-id needs the device UUID." >&2; exit 2; fi
      CLIENT_ID="$2"; shift 2 ;;
    --pairing-token)
      if (($# < 2)) || [[ -z "$2" ]]; then echo "--pairing-token needs the per-device token." >&2; exit 2; fi
      PAIRING_TOKEN="$2"; shift 2 ;;
    *)
      echo "Unknown option: $1. Use --avatar-server-url ws://192.0.2.10:8766, --device-id <MAC> --client-id <UUID> --pairing-token <token>, --ca-file /path/to/ca.pem, or --no-persistent-websocket." >&2
      exit 2
      ;;
  esac
done
if [[ -n "$CA_FILE" ]]; then
  if [[ ! -f "$CA_FILE" || ! -r "$CA_FILE" ]]; then
    echo "CA PEM file is missing or unreadable: $CA_FILE. Check the path and file permissions." >&2
    exit 2
  fi
  CA_FILE=$(cd "$(dirname "$CA_FILE")" && pwd)/$(basename "$CA_FILE")
  if [[ "$CA_FILE" == *'"'* || "$CA_FILE" == *'\'* || "$CA_FILE" == *$'\n'* ]]; then
    echo "CA PEM path contains a character sdkconfig cannot represent: $CA_FILE. Move it to a simple path and retry." >&2
    exit 2
  fi
  if ! openssl x509 -in "$CA_FILE" -noout >/dev/null 2>&1; then
    echo "CA PEM file is not a readable X.509 certificate: $CA_FILE. Provide a CA certificate in PEM format." >&2
    exit 2
  fi
fi
if [[ -n "$AVATAR_SERVER_URL" && ! "$AVATAR_SERVER_URL" =~ ^wss?://[^/[:space:]]+(/[^[:space:]]*)?$ ]]; then
  echo "Invalid avatar server URL: use ws:// or wss:// followed by a host and optional path." >&2
  exit 2
fi
if [[ -n "$DEVICE_ID" && ! "$DEVICE_ID" =~ ^([[:xdigit:]]{2}:){5}[[:xdigit:]]{2}$ ]]; then
  echo "Invalid Device-Id; use the device MAC address (for example 02:00:00:00:00:15)." >&2; exit 2
fi
if [[ -n "$DEVICE_ID" && -z "$CLIENT_ID" ]] || [[ -n "$CLIENT_ID" && -z "$DEVICE_ID" ]]; then
  echo "--device-id and --client-id must be provided together." >&2; exit 2
fi
if [[ -n "$PAIRING_TOKEN" && -z "$DEVICE_ID" ]]; then
  echo "--pairing-token requires --device-id and --client-id." >&2; exit 2
fi
if [[ -n "$DEVICE_ID" && -z "$PAIRING_TOKEN" ]]; then
  echo "--pairing-token is required with the avatar Device-Id and Client-Id." >&2; exit 2
fi
if [[ -n "$CLIENT_ID" && ! "$CLIENT_ID" =~ ^[[:xdigit:]]{8}-([[:xdigit:]]{4}-){3}[[:xdigit:]]{12}$ ]]; then
  echo "Invalid Client-Id; use a UUID." >&2; exit 2
fi
ESP_IDF_VERSION=$(python3 - "$PIN_FILE" <<'PY'
import sys, tomllib
print(tomllib.load(open(sys.argv[1], 'rb'))['toolchain']['esp_idf'])
PY
)
BUILD_ROOT="${STACKCHAN_BUILD_ROOT:-$HOME/esp/stackchan-build/stackchan-02-run/build}"
SRC="$BUILD_ROOT/StackChan"
OUT="$BUILD_ROOT/output"
PINNED_LOCK="$HERE/pins/dependencies.lock"

IDF_EXPORT="${IDF_EXPORT:-$HOME/esp/esp-idf/export.sh}"
if [[ ! -f "$IDF_EXPORT" ]]; then
  echo "ESP-IDF export script is missing at $IDF_EXPORT. Install ESP-IDF 5.5.4 and retry." >&2
  exit 2
fi
# shellcheck disable=SC1090
. "$IDF_EXPORT" >/dev/null
if ! idf.py --version | grep -Fq "$ESP_IDF_VERSION"; then
  echo "ESP-IDF version does not match pins.toml ($ESP_IDF_VERSION). Install the pinned toolchain and retry." >&2
  exit 1
fi

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
LOCK_HASH=$(read_pin stackchan dependencies_lock_sha256)
mkdir -p "$BUILD_ROOT" "$OUT"
# The build config and app image hold the pairing token; keep them to this account.
chmod 700 "$BUILD_ROOT"
CREATED_SRC=0
if [[ ! -d "$SRC/.git" ]]; then
  git clone --no-checkout "$STACKCHAN_URL" "$SRC"
  CREATED_SRC=1
fi
if [[ "$CREATED_SRC" == "0" && -n "$(git -C "$SRC" status --porcelain)" ]]; then
  echo "StackChan source tree has local changes at $SRC. Preserve or remove them, then retry." >&2
  exit 1
fi
git -C "$SRC" fetch --no-tags "$STACKCHAN_URL" "$STACKCHAN_COMMIT"
git -C "$SRC" checkout --detach "$STACKCHAN_COMMIT"
[[ "$(git -C "$SRC" rev-parse HEAD)" == "$STACKCHAN_COMMIT" ]] || { echo "StackChan checkout does not match pins.toml. Check the repository and retry." >&2; exit 1; }
# GCC substitutes SOURCE_DATE_EPOCH for __DATE__ and __TIME__, making the app descriptor stable.
export SOURCE_DATE_EPOCH="$(git -C "$SRC" show -s --format=%ct "$STACKCHAN_COMMIT")"
FW="$SRC/firmware"
actual_repos_hash=$(shasum -a 256 "$FW/repos.json" | awk '{print $1}')
[[ "$actual_repos_hash" == "$REPOS_HASH" ]] || { echo "repos.json checksum changed from pins.toml. Review dependency pins before building." >&2; exit 1; }
actual_lock_hash=$(shasum -a 256 "$FW/dependencies.lock" | awk '{print $1}')
[[ "$actual_lock_hash" == "$LOCK_HASH" ]] || { echo "dependencies.lock differs from pins/dependencies.lock. Review registry component pins before building." >&2; exit 1; }
cmp -s "$FW/dependencies.lock" "$PINNED_LOCK" || { echo "dependencies.lock differs from the checked-in registry lock. Review and update the lock pin." >&2; exit 1; }

APPLIED_REPO_PATCHES=()
LOCAL_CONFIG="$FW/sdkconfig.defaults.local"
LOCAL_CONFIG_BACKUP="$BUILD_ROOT/sdkconfig.defaults.local.previous"
LOCAL_CONFIG_EXISTED=0
SDKCONFIG="$FW/sdkconfig"
SDKCONFIG_BACKUP="$BUILD_ROOT/sdkconfig.previous"
SDKCONFIG_EXISTED=0
if [[ -e "$LOCAL_CONFIG" ]]; then
  cp -p "$LOCAL_CONFIG" "$LOCAL_CONFIG_BACKUP"
  LOCAL_CONFIG_EXISTED=1
fi
if [[ -e "$SDKCONFIG" ]]; then
  cp -p "$SDKCONFIG" "$SDKCONFIG_BACKUP"
  SDKCONFIG_EXISTED=1
fi
cleanup_firmware_tree() {
  local entry patch_file target i temp="$BUILD_ROOT/patch-cleanup.tmp"
  for ((i=${#APPLIED_REPO_PATCHES[@]}-1; i>=0; i--)); do
    entry=${APPLIED_REPO_PATCHES[$i]}
    patch_file=${entry%%:*}
    target=${entry#*:}
    sed -n '/^diff --git/,$p' "$HERE/patches/$patch_file" > "$temp"
    git -C "$target" apply --unidiff-zero --reverse "$temp"
  done
  python3 - "$FW" <<'PY'
import json, subprocess, sys
from pathlib import Path
fw = Path(sys.argv[1])
for item in json.loads((fw / 'repos.json').read_text()):
    patch_name = item.get('patch')
    path = fw / item['path']
    if patch_name:
        patch = fw / patch_name
        check = subprocess.run(['git', '-C', str(path), 'apply', '--reverse', '--check', str(patch)])
        if check.returncode == 0:
            subprocess.run(['git', '-C', str(path), 'apply', '--reverse', str(patch)], check=True)
PY
  if [[ "$LOCAL_CONFIG_EXISTED" == "1" ]]; then
    cp -p "$LOCAL_CONFIG_BACKUP" "$LOCAL_CONFIG"
  else
    rm -f "$LOCAL_CONFIG"
  fi
  if [[ "$SDKCONFIG_EXISTED" == "1" ]]; then
    cp -p "$SDKCONFIG_BACKUP" "$SDKCONFIG"
  else
    rm -f "$SDKCONFIG"
  fi
  # Put back the launcher assets the build pruned (patch 049's assets step) so the pinned tree is clean.
  git -C "$SRC" checkout -- firmware/main/assets/assets_bin
  if [[ -n "$(git -C "$SRC" status --porcelain)" ]]; then
    echo "Firmware recipe left changes in $SRC. Inspect this source tree before retrying." >&2
    return 1
  fi
}
trap cleanup_firmware_tree EXIT

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
    if not (path / '.git').exists():
        subprocess.run(['git', 'clone', '--no-checkout', item['url'], str(path)], check=True)
    elif subprocess.check_output(['git', '-C', str(path), 'status', '--porcelain'], text=True).strip():
        raise SystemExit(f'Pinned dependency has local changes at {item["path"]}; preserve or remove them first')
    subprocess.run(['git', '-C', str(path), 'fetch', '--no-tags', item['url'], expected[item['path']]], check=True)
    subprocess.run(['git', '-C', str(path), 'checkout', '--detach', expected[item['path']]], check=True)
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
  APPLIED_REPO_PATCHES+=("$patch_file:$target")
  echo "PATCH-OK: $patch_file"
}
apply_repo_patch 001-server-url-empty.patch "$SRC"
apply_repo_patch 002-nvs-websocket-no-ota.patch "$SRC"
apply_repo_patch 003-stackchan-kconfig.patch "$SRC"
apply_repo_patch 003-persistent-websocket.patch "$FW/xiaozhi-esp32"
apply_repo_patch 004-configurable-sntp-empty.patch "$SRC"
apply_repo_patch 005-disable-m5-registry-mqtt.patch "$SRC"
apply_repo_patch 007-unique-firmware-identity.patch "$SRC"
apply_repo_patch 008-additional-ca-bundle.patch "$SRC"
apply_repo_patch 009-axp2101-charging-timeout.patch "$FW/xiaozhi-esp32"
apply_repo_patch 010-battery-status.patch "$SRC"
apply_repo_patch 011-avatar-auth-headers.patch "$SRC"
apply_repo_patch 012-per-pixel-led-tool.patch "$SRC"
apply_repo_patch 013-mint-face-skin.patch "$SRC"
apply_repo_patch 014-wifi-awake-while-speaking.patch "$SRC"
apply_repo_patch 015-speech-edges.patch "$SRC"
apply_repo_patch 016-speech-open-at-tts-start.patch "$SRC"
apply_repo_patch 017-face-palette-idle-light.patch "$SRC"
apply_repo_patch 018-hello-token-handoff.patch "$FW/xiaozhi-esp32"
apply_repo_patch 019-avatar-nvs-config.patch "$SRC"
apply_repo_patch 020-dance-mcp-tools.patch "$SRC"
apply_repo_patch 021-device-events-tool.patch "$SRC"
apply_repo_patch 023-wifi-saved-networks-tools.patch "$SRC"
apply_repo_patch 030-load-local-assets.patch "$SRC"
apply_repo_patch 032-wake-word-with-persistent-socket.patch "$SRC"
apply_repo_patch 033-connecting-screen-and-boot-ring.patch "$SRC"
apply_repo_patch 034-host-idle-command.patch "$SRC"
apply_repo_patch 036-swipe-gestures-and-quick-settings.patch "$SRC"
apply_repo_patch 037-idle-motion-off-by-default.patch "$SRC"
apply_repo_patch 038-head-move-cap.patch "$SRC"
apply_repo_patch 039-mcp-timing-log.patch "$SRC"
apply_repo_patch 044-strongest-wifi-ap.patch "$SRC"
apply_repo_patch 046-touch-diagnostics.patch "$SRC"
apply_repo_patch 047-tap-handling.patch "$SRC"
apply_repo_patch 048-head-touch-filter.patch "$SRC"
apply_repo_patch 049-stop-word.patch "$SRC"
apply_repo_patch 050-ring-dark-with-screen.patch "$SRC"
apply_repo_patch 051-internal-ram-budget.patch "$SRC"
apply_repo_patch 052-rub-detection.patch "$SRC"
apply_repo_patch 053-stable-stacks.patch "$SRC"
apply_repo_patch 054-avatar-channel-in-agent-mode.patch "$SRC"
apply_repo_patch 055-opus-stack-in-psram-experiment.patch "$SRC"
apply_repo_patch 056-pet-by-peak-reading.patch "$SRC"
apply_repo_patch 057-shake-threshold.patch "$SRC"
apply_repo_patch 058-internal-ram-trims.patch "$SRC"

# Room in the 4 MB assets partition for the stop-word model (mn5q8_en, about 2.2 MB): drop the
# launcher icons and artwork of the Mooncake apps, which this firmware never starts (it boots
# straight into the voice agent). A missing image is logged and drawn blank by assets::get_image,
# never a crash. Kept: the Wi-Fi, battery, bell, home and indicator icons.
for asset in icon_ai_agent.bin icon_app_center.bin icon_controller.bin icon_dance.bin \
    icon_ezdata.bin icon_sentinel.bin icon_setup.bin setup_stackchan_front_view.bin app_center_bg.png; do
  rm -f "$FW/main/assets/assets_bin/$asset"
done

cat > "$FW/sdkconfig.defaults.local" <<CFG
CONFIG_STACKCHAN_SERVER_URL="$AVATAR_SERVER_URL"
CONFIG_OTA_URL=""
CONFIG_STACKCHAN_NTP_SERVER=""
CONFIG_STACKCHAN_XIAOZHI_OTA_CHECK=n
CONFIG_SR_MN_EN_MULTINET5_SINGLE_RECOGNITION_QUANT8=y
CFG
if [[ -n "$DEVICE_ID" ]]; then
  printf 'CONFIG_STACKCHAN_DEVICE_ID="%s"\n' "$DEVICE_ID" >> "$FW/sdkconfig.defaults.local"
fi
if [[ -n "$CLIENT_ID" ]]; then
  printf 'CONFIG_STACKCHAN_CLIENT_ID="%s"\n' "$CLIENT_ID" >> "$FW/sdkconfig.defaults.local"
fi
if [[ -n "$PAIRING_TOKEN" ]]; then
  if [[ "$PAIRING_TOKEN" == *'"'* || "$PAIRING_TOKEN" == *'\'* || "$PAIRING_TOKEN" == *$'\n'* ]]; then
    echo "Pairing token contains a character sdkconfig cannot represent." >&2; exit 2
  fi
  printf 'CONFIG_STACKCHAN_PAIRING_TOKEN="%s"\n' "$PAIRING_TOKEN" >> "$FW/sdkconfig.defaults.local"
fi
if [[ "$PERSISTENT_WEBSOCKET" == "n" ]]; then
  echo 'CONFIG_STACKCHAN_PERSISTENT_WEBSOCKET=n' >> "$FW/sdkconfig.defaults.local"
fi
if [[ -n "$CA_FILE" ]]; then
  python3 - "$FW/sdkconfig.defaults.local" "$CA_FILE" <<'PY'
import json, sys
from pathlib import Path
config = Path(sys.argv[1])
path = json.dumps(sys.argv[2])
with config.open('a') as stream:
    stream.write(f'CONFIG_STACKCHAN_CA_PEM={path}\n')
    stream.write('CONFIG_MBEDTLS_CERTIFICATE_BUNDLE=y\n')
    stream.write('CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE=y\n')
    stream.write(f'CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH={path}\n')
PY
else
  cat >> "$FW/sdkconfig.defaults.local" <<'CFG'
CONFIG_STACKCHAN_CA_PEM=""
CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE=n
CFG
fi

if [[ "${STACKCHAN_CHECK_ONLY:-0}" == "1" ]]; then
  rm -f "$SDKCONFIG"
  (cd "$FW" && idf.py reconfigure)
else
  (cd "$FW" && idf.py fullclean)
  rm -f "$SDKCONFIG"
  (cd "$FW" && idf.py build)
fi
if [[ "$PERSISTENT_WEBSOCKET" == "n" ]]; then
  grep -Fqx '# CONFIG_STACKCHAN_PERSISTENT_WEBSOCKET is not set' "$SDKCONFIG" || { echo "Persistent websocket should be disabled by --no-persistent-websocket. Check sdkconfig defaults and retry." >&2; exit 1; }
else
  grep -Fqx 'CONFIG_STACKCHAN_PERSISTENT_WEBSOCKET=y' "$SDKCONFIG" || { echo "Persistent websocket should default to enabled for this profile. Check the StackChan Kconfig patch and retry." >&2; exit 1; }
fi
if [[ -n "$CA_FILE" ]]; then
  grep -Fqx "CONFIG_STACKCHAN_CA_PEM=\"$CA_FILE\"" "$SDKCONFIG" || { echo "CA path was not selected in sdkconfig. Check the PEM path and retry." >&2; exit 1; }
  grep -Fqx "CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE=y" "$SDKCONFIG" || { echo "ESP-IDF did not enable the custom CA bundle. Confirm the pinned ESP-IDF config and retry." >&2; exit 1; }
  grep -Fqx "CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH=\"$CA_FILE\"" "$SDKCONFIG" || { echo "ESP-IDF did not select the provided CA bundle file. Check the path and retry." >&2; exit 1; }
else
  grep -Fqx 'CONFIG_STACKCHAN_CA_PEM=""' "$SDKCONFIG" || { echo "CA path should be empty when --ca-file is omitted. Check sdkconfig defaults and retry." >&2; exit 1; }
  grep -Fqx '# CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE is not set' "$SDKCONFIG" || { echo "Custom CA bundle should be disabled when --ca-file is omitted. Check sdkconfig defaults and retry." >&2; exit 1; }
fi
if [[ "${STACKCHAN_CHECK_ONLY:-0}" == "1" ]]; then
  echo PATCHES-AND-KCONFIG-OK
  exit 0
fi
echo BUILD-OK
image="$FW/build/maipai-stackchan.bin"
"$HERE/host-search.sh" "$image"
mkdir -p "$OUT"
idf.py --version > "$OUT/idf-version.txt"
xtensa-esp-elf-gcc --version > "$OUT/xtensa-version.txt"
shasum -a 256 "$(command -v python3)" > "$OUT/python-runtime.sha256"
python3 -m pip freeze | LC_ALL=C sort | shasum -a 256 > "$OUT/python-environment.sha256"
cp "$image" "$OUT/stack-chan-maipai.bin"
ASSETS_BYTES=$(wc -c < "$FW/build/generated_assets.bin")
if (( ASSETS_BYTES > 4194304 )); then
  echo "The assets image is $ASSETS_BYTES bytes and does not fit the 4 MB assets partition. Prune more launcher assets or drop the stop-word model." >&2
  exit 1
fi
cp "$FW/build/generated_assets.bin" "$OUT/"
cp "$FW/build/ota_data_initial.bin" "$OUT/"
(cd "$OUT" && shasum -a 256 stack-chan-maipai.bin generated_assets.bin ota_data_initial.bin idf-version.txt xtensa-version.txt python-runtime.sha256 python-environment.sha256 > SHA256SUMS)
cat "$OUT/SHA256SUMS"
