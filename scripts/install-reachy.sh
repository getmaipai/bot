#!/usr/bin/env bash
# Install MaiPai Bot on a Reachy Mini unit over SSH: copy the wheel, pip
# install it into the daemon's shared apps venv, register it as the
# startup app, and restart the daemon.
#
# Usage: scripts/install-reachy.sh [--dry-run] <host> <wheel-path>
#   host        the robot's hostname or IP
#   wheel-path  a built maipai-bot wheel, e.g. from `uv build --wheel`
#               in body/, or scripts/build-space.sh's dist/space/
#
# Auth is whatever the caller's own `ssh` already has configured (a key,
# an agent, an interactive prompt): this script never accepts, stores,
# prints, or embeds a password. Rotating the robot's own published
# default password is a Home flow (RM-08), not this script's job.
#
# Idempotent: safe to re-run against the same host and wheel.
#
# The wheel built from body/'s own pyproject.toml carries no simulator:
# `mujoco` moved to an opt-in `sim` extra (G12,
# docs/dev/reachy-mini-gap-audit-2026-09-27.md), so `pip install` of the
# bare wheel on the robot pulls only its runtime dependencies.
set -euo pipefail

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
  shift
fi

if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--dry-run] <host> <wheel-path>" >&2
  exit 1
fi

HOST="$1"
WHEEL_PATH="$2"
SSH_USER="${MAIPAI_REACHY_SSH_USER:-pollen}"
APPS_VENV="/venvs/apps_venv"
APP_NAME="maipai_bot"
DAEMON_PORT="${MAIPAI_REACHY_DAEMON_PORT:-8000}"
# Reachy Eyes serial access (EYES-06): the fixed, checked USB identity
# lives in reachy-eyes-setup.sh so the installer accepts no arbitrary IDs.
EYES_SETUP="$(dirname "$0")/udev/reachy-eyes-setup.sh"
ROBOT_CONF="$(dirname "$0")/robot-conf/configure.sh"
ROBOT_NFT="$(dirname "$0")/robot-conf/maipai.nft"
HUB_ADDRESS="${MAIPAI_REACHY_HUB_ADDRESS:-}"
ROUTER_ADDRESS="${MAIPAI_REACHY_ROUTER_ADDRESS:-}"
ROBOT_SUBNET="${MAIPAI_REACHY_SUBNET:-}"

WHEEL_FILE="$(basename "$WHEEL_PATH")"
REMOTE_WHEEL="/tmp/$WHEEL_FILE"
RELEASE_VERSION="${WHEEL_FILE#maipai_bot-}"
RELEASE_VERSION="${RELEASE_VERSION%%-*}"
WHEELHOUSE="$(dirname "$WHEEL_PATH")/maipai_bot-$RELEASE_VERSION-wheelhouse-aarch64-cp312.tar"
REMOTE_WHEELHOUSE="/tmp/$(basename "$WHEELHOUSE")"
REMOTE_WHEELHOUSE_DIR="/tmp/maipai-wheelhouse-$RELEASE_VERSION"
REMOTE_WHEEL_SHA="$WHEEL_PATH.sha256"
REMOTE_WHEELHOUSE_SHA="$WHEELHOUSE.sha256"

if [ "$DRY_RUN" = 1 ]; then
  for value in "$HUB_ADDRESS" "$ROUTER_ADDRESS" "$ROBOT_SUBNET"; do
    if [ -z "$value" ]; then
      echo "set MAIPAI_REACHY_HUB_ADDRESS, MAIPAI_REACHY_ROUTER_ADDRESS and MAIPAI_REACHY_SUBNET" >&2
      exit 1
    fi
  done
  printf 'daemon pin: reachy-mini==1.11.0\n'
  printf 'daemon flags: --dataset-update-interval 0 --no-preload-datasets --fastapi-host 127.0.0.1\n'
  printf 'daemon environment: HF_HUB_OFFLINE=1 MALLOC_ARENA_MAX=2; HTTP_PROXY unset\n'
  printf 'daemon config: turn_enabled=false; DELETE /api/hf-auth/token; verify read-back\n'
  printf 'firewall: nftables hub-only egress; hub-only SSH; tailnet opt-in; DHCP DNS mDNS\n'
  printf 'masked timers: systemd-timesyncd.service apt-daily.timer apt-daily-upgrade.timer\n'
  printf 'settings app: http://127.0.0.1:8042\n'
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "test \"\$(/venvs/apps_venv/bin/pip show reachy-mini | sed -n 's/^Version: //p')\" = 1.11.0"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "sudo rm -f /home/pollen/.cache/huggingface/token /home/pollen/.huggingface/token"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "curl -sf -X DELETE http://127.0.0.1:$DAEMON_PORT/api/hf-auth/token"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "sudo python3 -c 'import json,pathlib; p=pathlib.Path(\"/home/pollen/.config/reachy_mini/daemon_config.json\"); d=json.loads(p.read_text()) if p.exists() else {}; d[\"turn_enabled\"]=False; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,indent=2)+\"\\n\"); assert json.loads(p.read_text())[\"turn_enabled\"] is False'"
  printf 'scp %q %q %q\n' "$ROBOT_CONF" "$ROBOT_NFT" "$SSH_USER@$HOST:/tmp/"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "sudo bash /tmp/configure.sh '$HUB_ADDRESS' '$ROUTER_ADDRESS' '$ROBOT_SUBNET' '${MAIPAI_TAILNET_ENABLED:-0}' /tmp/maipai.nft"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "sudo systemctl enable nftables.service"
  printf 'release payload: %s %s and SHA-256 sidecars\n' "$WHEEL_FILE" "$(basename "$WHEELHOUSE")"
  printf 'local validation: sha256sum -c %q; tar contains onnxruntime-1.30.0 aarch64 and sherpa_onnx aarch64 wheels\n' "$REMOTE_WHEELHOUSE_SHA"
  printf 'install mode: pip install --no-index --find-links <wheelhouse> --no-deps; all requirements come from its lock file\n'
  printf 'scp %q %q %q %q %q\n' "$WHEEL_PATH" "$REMOTE_WHEEL_SHA" "$WHEELHOUSE" "$REMOTE_WHEELHOUSE_SHA" "$SSH_USER@$HOST:/tmp/"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "sha256sum -c /tmp/$(basename "$REMOTE_WHEEL_SHA") && sha256sum -c /tmp/$(basename "$REMOTE_WHEELHOUSE_SHA")"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "mkdir -p '$REMOTE_WHEELHOUSE_DIR' && tar -xf '$REMOTE_WHEELHOUSE' -C '$REMOTE_WHEELHOUSE_DIR'"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "python3 -c check-pinned-reachy-mini-wheel-for-posthog; fail-if-found"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "$APPS_VENV/bin/pip install --no-index --find-links '$REMOTE_WHEELHOUSE_DIR' --no-deps --force-reinstall '$REMOTE_WHEEL'"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "$APPS_VENV/bin/pip install --no-index --find-links '$REMOTE_WHEELHOUSE_DIR' --no-deps --force-reinstall -r '$REMOTE_WHEELHOUSE_DIR/requirements-aarch64-cp312.txt'"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "curl -sf -X PUT http://localhost:$DAEMON_PORT/api/apps/startup-app -H 'Content-Type: application/json' -d '{\"startup_app\": \"$APP_NAME\"}'"
  printf 'ssh %q %q <<'\''REMOVE_VENDOR_APPS'\''\n' "$SSH_USER@$HOST" "python3 - $DAEMON_PORT $APP_NAME"
  sed 's/^/  /' < <(sed -n '/^import json$/,/^REMOVE_VENDOR_APPS$/p' "$0" | sed '$d')
  printf 'REMOVE_VENDOR_APPS\n'
  printf 'ssh %q %q < %q\n' "$SSH_USER@$HOST" "sudo bash -s" "$EYES_SETUP"
  printf 'ssh %s "sudo systemctl restart reachy-mini-daemon"\n' "$SSH_USER@$HOST"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "rm -f '$REMOTE_WHEEL'"
  exit 0
fi

for value in "$HUB_ADDRESS" "$ROUTER_ADDRESS" "$ROBOT_SUBNET"; do
  if [ -z "$value" ]; then
    echo "set MAIPAI_REACHY_HUB_ADDRESS, MAIPAI_REACHY_ROUTER_ADDRESS and MAIPAI_REACHY_SUBNET" >&2
    exit 1
  fi
done

if [ ! -f "$WHEEL_PATH" ]; then
  echo "wheel not found: $WHEEL_PATH" >&2
  exit 1
fi
if [ ! -f "$WHEELHOUSE" ] || [ ! -f "$REMOTE_WHEEL_SHA" ] || [ ! -f "$REMOTE_WHEELHOUSE_SHA" ]; then
  echo "wheelhouse or SHA-256 sidecars missing beside release wheel" >&2
  exit 1
fi
(
  cd "$(dirname "$WHEEL_PATH")"
  sha256sum -c "$(basename "$REMOTE_WHEEL_SHA")" 2>/dev/null || shasum -a 256 -c "$(basename "$REMOTE_WHEEL_SHA")"
  sha256sum -c "$(basename "$REMOTE_WHEELHOUSE_SHA")" 2>/dev/null || shasum -a 256 -c "$(basename "$REMOTE_WHEELHOUSE_SHA")"
  tar -tf "$(basename "$WHEELHOUSE")" | rg -q 'onnxruntime-1\.30\.0-.*aarch64.*\.whl$'
  tar -tf "$(basename "$WHEELHOUSE")" | rg -q 'sherpa[_-]onnx-.*aarch64.*\.whl$'
)

echo "== copying $WHEEL_FILE to $SSH_USER@$HOST:$REMOTE_WHEEL"
scp "$WHEEL_PATH" "$REMOTE_WHEEL_SHA" "$WHEELHOUSE" "$REMOTE_WHEELHOUSE_SHA" "$SSH_USER@$HOST:/tmp/"

echo "== verifying release checksums"
ssh "$SSH_USER@$HOST" "cd /tmp && sha256sum -c '$(basename "$REMOTE_WHEEL_SHA")' && sha256sum -c '$(basename "$REMOTE_WHEELHOUSE_SHA")'"
ssh "$SSH_USER@$HOST" "mkdir -p '$REMOTE_WHEELHOUSE_DIR' && tar -xf '$REMOTE_WHEELHOUSE' -C '$REMOTE_WHEELHOUSE_DIR'"
ssh "$SSH_USER@$HOST" "python3 -c 'import glob,zipfile,sys; p=glob.glob(\"$REMOTE_WHEELHOUSE_DIR/reachy_mini-1.11.0-*.whl\"); assert len(p)==1, p; z=zipfile.ZipFile(p[0]); bad=[n for n in z.namelist() if n.endswith((\".py\",\".json\")) and b\"posthog\" in z.read(n).lower()]; print(bad); sys.exit(bool(bad))'"

echo "== installing into $APPS_VENV"
REMOTE_VERSION="$(ssh "$SSH_USER@$HOST" "$APPS_VENV/bin/pip show reachy-mini | sed -n 's/^Version: //p'")"
if [ "$REMOTE_VERSION" != "1.11.0" ]; then
  echo "Reachy daemon version is '$REMOTE_VERSION'; this Bot release requires exactly 1.11.0" >&2
  exit 1
fi
# [voice]: G2's wake-word scoring is core to a conversational robot, not
# an optional extra an operator has to remember to ask for separately.
ssh "$SSH_USER@$HOST" "$APPS_VENV/bin/pip install --no-index --find-links '$REMOTE_WHEELHOUSE_DIR' --no-deps --force-reinstall '$REMOTE_WHEEL'"

# All transitive wheels are resolved by uv from pyproject.toml and staged
# in the release archive. `--no-deps` preserves uv's onnxruntime 1.30.0
# override over reachy-mini's upstream 1.27.0 metadata pin.
echo "== installing the locked dependencies from the offline wheelhouse"
ssh "$SSH_USER@$HOST" "$APPS_VENV/bin/pip install --no-index --find-links '$REMOTE_WHEELHOUSE_DIR' --no-deps --force-reinstall -r '$REMOTE_WHEELHOUSE_DIR/requirements-aarch64-cp312.txt'"

echo "== registering $APP_NAME as the startup app"
ssh "$SSH_USER@$HOST" \
  "curl -sf -X PUT http://localhost:$DAEMON_PORT/api/apps/startup-app \
    -H 'Content-Type: application/json' \
    -d '{\"startup_app\": \"$APP_NAME\"}'"

echo "== removing vendor apps (design record: 'any app the unit ships with is removed by the install step')"
ssh "$SSH_USER@$HOST" python3 - "$DAEMON_PORT" "$APP_NAME" <<'REMOVE_VENDOR_APPS'
import json
import sys
import time
import urllib.request

port, keep = sys.argv[1], sys.argv[2]
base = f"http://localhost:{port}/api/apps"

with urllib.request.urlopen(f"{base}/list-available/installed") as resp:
    installed = json.load(resp)

# maipai_bot is already registered as the startup app by the time this
# runs (the daemon's own "installed" listing is entry points in the
# shared apps_venv - reachy_mini_apps - which now includes it), so
# excluding it by name is what keeps this idempotent on a re-run rather
# than removing and immediately needing to reinstall our own app.
vendor_apps = [app["name"] for app in installed if app["name"] != keep]
if not vendor_apps:
    print("no vendor apps installed")
    sys.exit(0)

for name in vendor_apps:
    print(f"removing {name}")
    req = urllib.request.Request(f"{base}/remove/{name}", method="POST")
    with urllib.request.urlopen(req) as resp:
        job_id = json.load(resp)["job_id"]

    for _ in range(30):
        with urllib.request.urlopen(f"{base}/job-status/{job_id}") as resp:
            job = json.load(resp)
        if job["status"] == "done":
            break
        if job["status"] == "failed":
            print(f"failed to remove {name}:\n" + "\n".join(job["logs"]), file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
    else:
        print(f"timed out removing {name}", file=sys.stderr)
        sys.exit(1)
    print(f"removed {name}")

# A code review (2026-09-27) found the daemon's own "done" status is not
# proof of anything: both pip and uv exit 0 with a "Skipping X as it is
# not installed" warning when the entry-point name doesn't match the
# actual distribution name (verified on this machine), so a job can
# report done while the app survives. Re-list rather than trust the
# job status.
with urllib.request.urlopen(f"{base}/list-available/installed") as resp:
    remaining = [app["name"] for app in json.load(resp) if app["name"] != keep]
if remaining:
    print(f"still installed after removal: {', '.join(remaining)}", file=sys.stderr)
    sys.exit(1)
REMOVE_VENDOR_APPS

echo "== disabling TURN relay and removing saved Hugging Face tokens"
ssh "$SSH_USER@$HOST" "sudo python3 -c 'import json,pathlib; p=pathlib.Path(\"/home/pollen/.config/reachy_mini/daemon_config.json\"); d=json.loads(p.read_text()) if p.exists() else {}; d[\"turn_enabled\"]=False; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,indent=2)+\"\\n\"); assert json.loads(p.read_text())[\"turn_enabled\"] is False'"
ssh "$SSH_USER@$HOST" "sudo rm -f /home/pollen/.cache/huggingface/token /home/pollen/.huggingface/token"
ssh "$SSH_USER@$HOST" "sudo test ! -e /home/pollen/.cache/huggingface/token && sudo test ! -e /home/pollen/.huggingface/token"
ssh "$SSH_USER@$HOST" "curl -sf -X DELETE http://127.0.0.1:$DAEMON_PORT/api/hf-auth/token"
scp "$ROBOT_CONF" "$ROBOT_NFT" "$SSH_USER@$HOST:/tmp/"
ssh "$SSH_USER@$HOST" "sudo bash /tmp/configure.sh '$HUB_ADDRESS' '$ROUTER_ADDRESS' '$ROBOT_SUBNET' '${MAIPAI_TAILNET_ENABLED:-0}' /tmp/maipai.nft"

echo "== eyes serial access (udev rule, dialout for the daemon's service user)"
ssh "$SSH_USER@$HOST" "sudo bash -s" < "$EYES_SETUP"

echo "== restarting reachy-mini-daemon"
ssh "$SSH_USER@$HOST" "sudo systemctl restart reachy-mini-daemon"

echo "== cleaning up the staged wheel"
ssh "$SSH_USER@$HOST" "rm -f '$REMOTE_WHEEL'"
ssh "$SSH_USER@$HOST" "rm -f '$REMOTE_WHEELHOUSE' '$REMOTE_WHEELHOUSE_SHA' '$REMOTE_WHEEL_SHA'; rm -rf '$REMOTE_WHEELHOUSE_DIR'"

echo "== done: $APP_NAME installed on $HOST"
