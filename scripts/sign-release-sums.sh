#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 3 || "$1" != "--signing-key" ]]; then
  echo "Usage: sign-release-sums.sh --signing-key PATH|keychain:ITEM <stage-dir>" >&2
  exit 2
fi
SIGNING_SPEC="$2"
STAGE="$3"
SUMS="$STAGE/SHA256SUMS"
[[ -f "$SUMS" ]] || { echo "Missing $SUMS; run the bundle and asset build scripts first." >&2; exit 1; }
ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
source "$ROOT/scripts/signing-key.sh"
resolve_signing_key "$SIGNING_SPEC"
umask 077
WORK=$(mktemp -d "${TMPDIR:-/tmp}/maipai-sums-sign.XXXXXX")
chmod 700 "$WORK"
trap 'rm -rf "$WORK"; signing_key_cleanup' EXIT
trap 'rm -rf "$WORK"; signing_key_cleanup; exit 130' INT
trap 'rm -rf "$WORK"; signing_key_cleanup; exit 143' TERM
PAYLOAD="$WORK/payload.json"
SIGNATURE="$WORK/signature.bin"
PUBLIC_DER="$WORK/public.der"
python3 - "$SUMS" "$PAYLOAD" <<'PY'
import hashlib, json, pathlib, sys
digest = hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()
pathlib.Path(sys.argv[2]).write_text(json.dumps({"sha256": digest}, sort_keys=True, separators=(",", ":")))
PY
openssl pkeyutl -sign -rawin -inkey "$SIGNING_KEY_PATH" -in "$PAYLOAD" -out "$SIGNATURE"
openssl pkey -in "$SIGNING_KEY_PATH" -pubout -outform DER -out "$PUBLIC_DER"
python3 - "$PAYLOAD" "$SIGNATURE" "$PUBLIC_DER" "$STAGE/SHA256SUMS.sig.json" <<'PY'
import base64, hashlib, json, pathlib, sys
payload, signature, der, output = map(pathlib.Path, sys.argv[1:])
pub = der.read_bytes()[-32:]
obj = {"signed": json.loads(payload.read_text()), "signatures": [{"keyid": hashlib.sha256(pub).hexdigest()[:16], "sig": base64.b64encode(signature.read_bytes()).decode("ascii")}]}
output.write_text(json.dumps(obj, separators=(",", ":")) + "\n")
PY
