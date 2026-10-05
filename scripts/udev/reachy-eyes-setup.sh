#!/usr/bin/env bash
# Give the daemon's service user serial access to the Reachy Eyes LED
# board: a udev rule (mode 0660, group dialout) keyed on the board's USB
# ids, and dialout membership for whichever user the daemon unit runs as.
#
# Reachy Eyes USB identity. Confirm with `lsusb` on the owner's unit at
# arrival; this value is an arrival-day probe, not vendor source.
EYES_USB_VENDOR_ID="2e8a"
EYES_USB_PRODUCT_ID="10fc"
# Usage (as root on the unit): reachy-eyes-setup.sh [usb-vid usb-pid]
#   optional ids are accepted only when they match the constants above
#
# Run by scripts/install-reachy.sh over SSH. Idempotent: the rule file is
# rewritten and udev reloaded only when its content changes, and the group
# is added only when missing. Installs no vendor code and no firmware.
set -euo pipefail

RULES_DIR="${MAIPAI_UDEV_RULES_DIR:-/etc/udev/rules.d}"
UNIT="${MAIPAI_REACHY_DAEMON_UNIT:-reachy-mini-daemon}"
RULE_FILE="$RULES_DIR/99-maipai-eyes.rules"

if [ "$#" -ne 0 ] && [ "$#" -ne 2 ]; then
  echo "usage: $0 [usb-vid usb-pid]" >&2
  exit 1
fi

normalize() {
  local id="${1#0x}"
  if ! [[ "$id" =~ ^[0-9a-fA-F]{4}$ ]]; then
    echo "not a four digit hex USB id: $1" >&2
    exit 1
  fi
  printf '%s' "$id" | tr '[:upper:]' '[:lower:]'
}
if [ "$#" -eq 2 ]; then
  VID="$(normalize "$1")"
  PID="$(normalize "$2")"
  if [ "$VID" != "$EYES_USB_VENDOR_ID" ] || [ "$PID" != "$EYES_USB_PRODUCT_ID" ]; then
    echo "USB ids must match the Reachy Eyes constants ($EYES_USB_VENDOR_ID:$EYES_USB_PRODUCT_ID)" >&2
    exit 1
  fi
fi

RULE="# Managed by MaiPai Bot's install step. Reachy Eyes serial port.
SUBSYSTEM==\"tty\", ATTRS{idVendor}==\"$EYES_USB_VENDOR_ID\", ATTRS{idProduct}==\"$EYES_USB_PRODUCT_ID\", MODE=\"0660\", GROUP=\"dialout\", SYMLINK+=\"maipai-eyes\", ENV{ID_MM_DEVICE_IGNORE}=\"1\""

if [ -f "$RULE_FILE" ] && [ "$(cat "$RULE_FILE")" = "$RULE" ]; then
  echo "udev rule already current"
else
  mkdir -p "$RULES_DIR"
  printf '%s\n' "$RULE" > "$RULE_FILE"
  udevadm control --reload-rules
  udevadm trigger --subsystem-match=tty
  echo "udev rule written: $RULE_FILE"
fi

# The service user comes from the daemon's own unit; an empty answer means
# the unit runs as root, which needs no group.
SERVICE_USER="$(systemctl show -p User --value "$UNIT" 2>/dev/null || true)"
if [ -z "$SERVICE_USER" ]; then
  echo "daemon unit $UNIT runs as root: no group change"
elif id -nG "$SERVICE_USER" | tr ' ' '\n' | grep -qx dialout; then
  echo "$SERVICE_USER is already in dialout"
else
  usermod -aG dialout "$SERVICE_USER"
  echo "added $SERVICE_USER to dialout (takes effect when the daemon restarts)"
fi
