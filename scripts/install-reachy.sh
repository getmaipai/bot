#!/usr/bin/env bash
# Install MaiPai Bot on a Reachy Mini unit over SSH: copy the wheel, pip
# install it into the daemon's shared apps venv, register it as the
# startup app, and restart the daemon.
#
# Usage: scripts/install-reachy.sh <host> <wheel-path>
#   host        the robot's hostname or IP (example: 192.0.2.10)
#   wheel-path  a built maipai-body wheel, e.g. from `uv build --wheel`
#               in body/, or scripts/build-space.sh's dist/space/
#
# Auth is whatever the caller's own `ssh` already has configured (a key,
# an agent, an interactive prompt): this script never accepts, stores,
# prints, or embeds a password. Rotating the robot's own published
# default password is a Home flow (RM-08), not this script's job.
#
# Idempotent: safe to re-run against the same host and wheel.
#
# Known gap: body/pyproject.toml currently pins reachy-mini[mujoco],
# which pulls the simulator onto the robot for no reason; splitting a
# real-hardware extra out is a follow-up before this script is used
# against a physical unit (docs/dev/design-reachy-mini-2026-09-27.md
# section 12, "the unit arrives").
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <host> <wheel-path>" >&2
  exit 1
fi

HOST="$1"
WHEEL_PATH="$2"
SSH_USER="${MAIPAI_REACHY_SSH_USER:-pollen}"
APPS_VENV="/venvs/apps_venv"
APP_NAME="maipai_bot"
DAEMON_PORT="${MAIPAI_REACHY_DAEMON_PORT:-8000}"

if [ ! -f "$WHEEL_PATH" ]; then
  echo "wheel not found: $WHEEL_PATH" >&2
  exit 1
fi

WHEEL_FILE="$(basename "$WHEEL_PATH")"
REMOTE_WHEEL="/tmp/$WHEEL_FILE"

echo "== copying $WHEEL_FILE to $SSH_USER@$HOST:$REMOTE_WHEEL"
scp "$WHEEL_PATH" "$SSH_USER@$HOST:$REMOTE_WHEEL"

echo "== installing into $APPS_VENV"
ssh "$SSH_USER@$HOST" "$APPS_VENV/bin/pip install --force-reinstall '$REMOTE_WHEEL'"

echo "== registering $APP_NAME as the startup app"
ssh "$SSH_USER@$HOST" \
  "curl -sf -X PUT http://localhost:$DAEMON_PORT/api/apps/startup-app \
    -H 'Content-Type: application/json' \
    -d '{\"startup_app\": \"$APP_NAME\"}'"

echo "== restarting reachy-mini-daemon"
ssh "$SSH_USER@$HOST" "sudo systemctl restart reachy-mini-daemon"

echo "== cleaning up the staged wheel"
ssh "$SSH_USER@$HOST" "rm -f '$REMOTE_WHEEL'"

echo "== done: $APP_NAME installed on $HOST"
