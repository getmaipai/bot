#!/usr/bin/env bash
# The documented offline install of MaiPai Bot onto a Reachy Mini: no
# Hugging Face account, no store token, no terminal for the family.
#
# Idempotent: running it again against the same host, with the same or a
# newer wheel, reinstalls cleanly rather than failing.
#
# SSH authentication is whatever the caller's own environment already
# provides (an agent key, ~/.ssh/config); this script never asks for,
# stores, prints, or embeds a password. Rotating the robot's published
# default password into Home's credentials center is Home's own install
# flow (RM-08), not this script's job, and neither is removing the
# vendor's preinstalled apps (also RM-08, once Home drives this end to
# end).
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/install-reachy.sh <host> <wheel-path>

  <host>        The robot's hostname or IP (its mDNS name works too:
                reachy-mini.local). Example in docs: 192.0.2.10.
  <wheel-path>  Path to the built maipai_body wheel (dist/*.whl).
USAGE
}

if [ "$#" -ne 2 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  usage >&2
  exit 1
fi

HOST="$1"
WHEEL_PATH="$2"
SSH_USER="${MAIPAI_REACHY_SSH_USER:-pollen}"
VENV="/venvs/apps_venv"

if [ ! -f "$WHEEL_PATH" ]; then
  echo "error: wheel not found at $WHEEL_PATH" >&2
  exit 1
fi

WHEEL_NAME="$(basename "$WHEEL_PATH")"

# A remote-generated temp path, never a predictable one built from the
# wheel's own name: a fixed `/tmp/<name>` path lets anything already on
# the robot pre-place a symlink there for scp to write through.
REMOTE_TMP="$(ssh "$SSH_USER@$HOST" mktemp)"

echo "== copying $WHEEL_NAME to $SSH_USER@$HOST:$REMOTE_TMP"
scp "$WHEEL_PATH" "$SSH_USER@$HOST:$REMOTE_TMP"

# ssh joins every trailing argument into one string for the remote shell,
# so a value is never passed as a separate argument the way a local
# command would take it: it is quoted here into the single command
# string ssh actually sends, or a value containing shell metacharacters
# would be interpreted remotely instead of treated as a literal path.
REMOTE_TMP_Q="$(printf '%q' "$REMOTE_TMP")"

echo "== installing into $VENV"
ssh "$SSH_USER@$HOST" "$VENV/bin/pip install --force-reinstall $REMOTE_TMP_Q"
ssh "$SSH_USER@$HOST" "rm -f $REMOTE_TMP_Q"

echo "== restarting reachy-mini-daemon so it sees the new app"
ssh "$SSH_USER@$HOST" sudo systemctl restart reachy-mini-daemon

echo "== done: maipai_body installed on $HOST"
