#!/usr/bin/env bash
# Store a key once with: security add-generic-password -s maipai-release-signing-key -a maipai -w "$(cat key.pem)" then delete the file.

# macOS /usr/bin/openssl is LibreSSL and cannot do Ed25519; prefer Homebrew's OpenSSL when it is installed.
for brew_ssl in /opt/homebrew/opt/openssl@3/bin /opt/homebrew/opt/openssl/bin /opt/homebrew/bin; do
  if [[ -x "$brew_ssl/openssl" ]]; then PATH="$brew_ssl:$PATH"; break; fi
done
export PATH

signing_key_cleanup() {
  [[ -z "${SIGNING_KEY_TMPDIR:-}" ]] || rm -rf "$SIGNING_KEY_TMPDIR"
}

resolve_signing_key() {
  local spec="$1"
  SIGNING_KEY_PATH=""
  if [[ "$spec" != keychain:* ]]; then
    [[ -f "$spec" && -r "$spec" ]] || { echo "Signing key is missing or unreadable: $spec" >&2; exit 2; }
    SIGNING_KEY_PATH="$spec"
    return 0
  fi

  local item="${spec#keychain:}" tmpdir
  [[ -n "$item" ]] || { echo "Keychain item name is empty; pass --signing-key keychain:ITEM." >&2; exit 2; }
  umask 077
  tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/maipai-signing-key.XXXXXX") || { echo "Could not create a private temporary directory for the signing key." >&2; exit 2; }
  chmod 700 "$tmpdir"
  # Global, so the traps still find it after this function returns. A caller that sets its own
  # traps later must call signing_key_cleanup in them.
  SIGNING_KEY_TMPDIR="$tmpdir"
  trap signing_key_cleanup EXIT
  trap 'signing_key_cleanup; exit 130' INT
  trap 'signing_key_cleanup; exit 143' TERM

  local raw="$tmpdir/keychain-output" key="$tmpdir/signing-key.pem"
  if ! "${MAIPAI_SECURITY_BIN:-security}" find-generic-password -s "$item" -w >"$raw"; then
    echo "Could not read signing key \"$item\" from the Keychain: unlock the login keychain (security unlock-keychain) or check the item name, then run the release again." >&2
    exit 2
  fi
  python3 - "$raw" "$key" <<'PY'
import pathlib, re, sys
data = pathlib.Path(sys.argv[1]).read_bytes().strip()
if not data.startswith(b"-----BEGIN") and re.fullmatch(rb"[0-9a-fA-F]+", data):
    data = bytes.fromhex(data.decode("ascii"))
pathlib.Path(sys.argv[2]).write_bytes(data)
PY
  chmod 600 "$key"
  rm -f "$raw"
  if ! openssl pkey -in "$key" -text -noout 2>/dev/null | grep -q 'ED25519'; then
    echo "Keychain item \"$item\" does not hold an Ed25519 private key PEM; store the release private key PEM in that Keychain item and run again." >&2
    exit 2
  fi
  # SIGNING_KEY_PATH is consumed by the script that sourced this file.
  # shellcheck disable=SC2034
  SIGNING_KEY_PATH="$key"
}
