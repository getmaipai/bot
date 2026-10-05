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

WHEEL_FILE="$(basename "$WHEEL_PATH")"
REMOTE_WHEEL="/tmp/$WHEEL_FILE"

if [ "$DRY_RUN" = 1 ]; then
  printf 'scp %q %q\n' "$WHEEL_PATH" "$SSH_USER@$HOST:$REMOTE_WHEEL"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "$APPS_VENV/bin/pip install --force-reinstall ${REMOTE_WHEEL}[voice]"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "pip install --force-reinstall onnxruntime==1.30.0"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "curl -sf -X PUT http://localhost:$DAEMON_PORT/api/apps/startup-app -H 'Content-Type: application/json' -d '{\"startup_app\": \"$APP_NAME\"}'"
  printf 'ssh %q %q <<'\''REMOVE_VENDOR_APPS'\''\n' "$SSH_USER@$HOST" "python3 - $DAEMON_PORT $APP_NAME"
  sed 's/^/  /' < <(sed -n '/^import json$/,/^REMOVE_VENDOR_APPS$/p' "$0" | sed '$d')
  printf 'REMOVE_VENDOR_APPS\n'
  printf 'ssh %s "sudo systemctl restart reachy-mini-daemon"\n' "$SSH_USER@$HOST"
  printf 'ssh %q %q\n' "$SSH_USER@$HOST" "rm -f '$REMOTE_WHEEL'"
  exit 0
fi

if [ ! -f "$WHEEL_PATH" ]; then
  echo "wheel not found: $WHEEL_PATH" >&2
  exit 1
fi

echo "== copying $WHEEL_FILE to $SSH_USER@$HOST:$REMOTE_WHEEL"
scp "$WHEEL_PATH" "$SSH_USER@$HOST:$REMOTE_WHEEL"

echo "== installing into $APPS_VENV"
# [voice]: G2's wake-word scoring is core to a conversational robot, not
# an optional extra an operator has to remember to ask for separately.
ssh "$SSH_USER@$HOST" "$APPS_VENV/bin/pip install --force-reinstall '${REMOTE_WHEEL}[voice]'"

# reachy-mini==1.11.0 hard-pins onnxruntime==1.27.0, verified (G2,
# docs/BACKLOG.md) to silently mis-score every wake-word inference with
# no error. The dev bench's `[tool.uv] override-dependencies` in
# body/pyproject.toml fixes this for `uv sync`, but that directive is
# uv-resolver-only - it never reaches a real install, and this script
# installs with plain pip over SSH, which would otherwise re-resolve
# straight back to reachy-mini's own broken pin (worse, the
# --force-reinstall above actively pulls it back down if a prior run
# somehow had the right version). Force it explicitly, every install,
# so this fix actually reaches the unit, not just the dev bench.
echo "== forcing onnxruntime to the version verified to score correctly (reachy-mini's own 1.27.0 pin silently breaks wake word)"
ssh "$SSH_USER@$HOST" "$APPS_VENV/bin/pip install --force-reinstall 'onnxruntime==1.30.0'"

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

echo "== restarting reachy-mini-daemon"
ssh "$SSH_USER@$HOST" "sudo systemctl restart reachy-mini-daemon"

echo "== cleaning up the staged wheel"
ssh "$SSH_USER@$HOST" "rm -f '$REMOTE_WHEEL'"

echo "== done: $APP_NAME installed on $HOST"
