#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$#" -ne 2 ]; then
  echo "usage: $0 <release-tag> <darwin-arm64|linux-x64|linux-arm64>" >&2
  exit 2
fi
TAG="$1"
PLATFORM="$2"
case "$PLATFORM" in
  # av ships macOS arm64 wheels for 14.0 and newer only, so the bundle targets macOS 14.
  darwin-arm64) TRIPLE=aarch64-apple-darwin; export MACOSX_DEPLOYMENT_TARGET=14.0 ;;
  linux-x64) TRIPLE=x86_64-unknown-linux-gnu ;;
  linux-arm64) TRIPLE=aarch64-unknown-linux-gnu ;;
  *) echo "unsupported platform $PLATFORM; choose darwin-arm64, linux-x64 or linux-arm64" >&2; exit 2 ;;
esac
VERSION="${TAG#v}"
DIST_STAGE="$ROOT/dist/bot-release/$TAG"
STAGE="${MAIPAI_BOT_BUNDLE_OUT_DIR:-$DIST_STAGE}"
if [[ "$STAGE" != /* ]]; then
  STAGE="$ROOT/$STAGE"
fi
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$STAGE"

# Reuse the release wheel preparation without invoking its legacy wheelhouse.
MAIPAI_SKIP_WHEELHOUSE=1 "$ROOT/scripts/prepare-bot-release.sh" "$TAG"
mkdir -p "$STAGE"
if [ "$STAGE" != "$DIST_STAGE" ]; then
  cp "$DIST_STAGE/maipai_bot-$VERSION-py3-none-any.whl" "$STAGE/"
  cp "$DIST_STAGE/maipai_bot-$VERSION-py3-none-any.whl.sha256" "$STAGE/"
fi
PIN="$(python3 - "$ROOT/scripts/hub-python-pins.json" "$PLATFORM" <<'PY'
import json, sys
print(json.dumps(json.load(open(sys.argv[1]))["platforms"][sys.argv[2]]))
PY
)"
URL="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["url"])' "$PIN")"
EXPECTED="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["sha256"])' "$PIN")"
if [[ ! "$EXPECTED" =~ ^[0-9a-f]{64}$ ]]; then
  echo "python sha256 pin for $PLATFORM is missing or invalid" >&2
  exit 1
fi
curl --fail --location --retry 3 "$URL" -o "$WORK/python.tar.gz"
ACTUAL="$(shasum -a 256 "$WORK/python.tar.gz" | awk '{print $1}')"
if [ "$ACTUAL" != "$EXPECTED" ]; then
  echo "python archive sha256 mismatch for $PLATFORM: expected $EXPECTED, got $ACTUAL" >&2
  exit 1
fi

mkdir -p "$WORK/python" "$STAGE"
tar -xzf "$WORK/python.tar.gz" -C "$WORK/python"
PYTHON="$WORK/python/python/bin/python3"
if [ ! -x "$PYTHON" ]; then
  echo "standalone Python archive did not contain python/install/bin/python3" >&2
  exit 1
fi
BOT="$WORK/bot"
mkdir -p "$BOT/bin" "$BOT/app"
# The app reads the shared vocabulary (robot API, capabilities, assets) from the pinned spec at run time.
SPEC_DIR="$("$ROOT/scripts/spec-dir.sh")"
rsync -aL --exclude node_modules --exclude .venv --exclude __pycache__ --exclude tests "$SPEC_DIR/" "$BOT/spec/"
cp -R "$WORK/python/python" "$BOT/python"
cp "$STAGE/maipai_bot-$VERSION-py3-none-any.whl" "$BOT/app/"

# Export the locked runtime; uv evaluates environment markers for the target.
# uv.lock resolves only for macOS (pyproject's [tool.uv] environments), so each target is compiled here for its own platform,
# hash-pinned, with every version the lock already holds as a constraint (the same route build-wheelhouse.sh takes for the robot).
uv run --no-project --python 3.12 python - "$ROOT/body/uv.lock" "$WORK/lock-constraints.txt" <<'PYC'
import pathlib, sys, tomllib
lock = tomllib.loads(pathlib.Path(sys.argv[1]).read_text())
pins = sorted({f"{p['name']}=={p['version']}" for p in lock.get('package', []) if 'version' in p and p.get('source', {}).get('registry')})
pathlib.Path(sys.argv[2]).write_text('\n'.join(pins) + '\n')
PYC
(cd "$ROOT/body" && uv pip compile pyproject.toml --extra hub --python-platform "$TRIPLE" --python-version 3.12 \
  --constraint "$WORK/lock-constraints.txt" --generate-hashes --no-header --output-file "$WORK/requirements.txt")
# A few locked dependencies publish only a source archive. They are pure Python, so building them on this host gives the same
# wheel for every target; the allow-list below names them, and the check after install refuses any that is not pure.
SDIST_ONLY="docopt"
uv run --no-project --python 3.12 python - "$WORK/requirements.txt" "$WORK/wheels.txt" "$WORK/sdists.txt" "$SDIST_ONLY" <<'PY0'
import pathlib, re, sys
source, wheels, sdists, allowed = sys.argv[1], sys.argv[2], sys.argv[3], set(sys.argv[4].split())
blocks, current = [], []
for line in pathlib.Path(source).read_text().splitlines():
    if line.strip().startswith('#') or not line.strip():
        continue
    if line[0] not in ' \t' and current:
        blocks.append(current)
        current = []
    current.append(line)
if current:
    blocks.append(current)
picked = {True: [], False: []}
for block in blocks:
    name = re.split(r'[<=>!~; \[]', block[0].strip(), maxsplit=1)[0].lower().replace('_', '-')
    picked[name in allowed].append('\n'.join(block))
pathlib.Path(wheels).write_text('\n'.join(picked[False]) + '\n')
pathlib.Path(sdists).write_text('\n'.join(picked[True]) + '\n')
PY0
uv pip install --python-platform "$TRIPLE" --python-version 3.12 --target "$BOT/app/site-packages" --only-binary :all: --no-deps --require-hashes -r "$WORK/wheels.txt"
if grep -q . "$WORK/sdists.txt"; then
  uv pip install --python-platform "$TRIPLE" --python-version 3.12 --target "$BOT/app/site-packages" --no-deps --require-hashes -r "$WORK/sdists.txt"
fi
uv pip install --python-platform "$TRIPLE" --python-version 3.12 --target "$BOT/app/site-packages" --no-deps "$BOT/app/maipai_bot-$VERSION-py3-none-any.whl"
uv run --no-project --python 3.12 python - "$WORK/requirements.txt" "$BOT/app/site-packages" "$SDIST_ONLY" <<'PY2'
import email, pathlib, re, sys
requirements = pathlib.Path(sys.argv[1]).read_text().splitlines()
names = {re.split(r'[<=>!~; \[]', line.strip(), maxsplit=1)[0].lower().replace('_', '-') for line in requirements if line.strip() and line[0] not in ' \t#-'}
installed = set()
for metadata in pathlib.Path(sys.argv[2]).glob('*.dist-info/METADATA'):
    with metadata.open() as f:
        installed.add(email.message_from_file(f).get('Name', '').lower().replace('_', '-'))
    wheel = metadata.with_name('WHEEL')
    if wheel.exists():
        with wheel.open() as f:
            tags = email.message_from_file(f).get_all('Tag') or []
        name = metadata.parent.name.split('-')[0].lower().replace('_', '-')
        if name in sys.argv[3].split() and not (tags and all(tag.endswith('-none-any') for tag in tags)):
            raise SystemExit(f'{name} built from source is not pure Python ({tags}); it cannot ship in a cross-target bundle')
missing = sorted(names - installed)
if missing:
    raise SystemExit('missing target distributions: ' + ', '.join(missing))
for script in pathlib.Path(sys.argv[2]).glob('bin/*'):
    if script.name in {'pip', 'pip3'} or script.name.startswith(('pip-', 'pip3.')):
        script.unlink()
PY2
cat > "$BOT/bin/maipai-bot-host" <<'SH'
#!/bin/sh
BASE="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
export PYTHONPATH="$BASE/app/site-packages"
export MAIPAI_SPEC_DIR="$BASE/spec"
exec "$BASE/python/bin/python3" -m maipai_body.hub_host "$@"
SH
chmod +x "$BOT/bin/maipai-bot-host"
ARCHIVE="$STAGE/bot-$PLATFORM.tar.gz"
COPYFILE_DISABLE=1 tar -czf "$ARCHIVE" -C "$WORK" bot
uv run --no-project --python 3.12 python - "$ARCHIVE" <<'PY2'
import pathlib, sys, tarfile
with tarfile.open(sys.argv[1], 'r:gz') as tar:
    for member in tar.getmembers():
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'bot':
            raise SystemExit(f'unsafe archive member: {member.name}')
        if member.issym() or member.islnk():
            target = pathlib.PurePosixPath(member.linkname)
            resolved = target if target.is_absolute() else path.parent / target
            stack = []
            for part in resolved.parts:
                if part in ('', '.', '/'):
                    continue
                if part == '..':
                    if stack: stack.pop()
                    else: raise SystemExit(f'outside archive symlink: {member.name}')
                else: stack.append(part)
            if not stack or stack[0] != 'bot':
                raise SystemExit(f'outside archive symlink: {member.name}')
PY2
SUMS="$STAGE/SHA256SUMS"
if [ -f "$SUMS" ]; then
  awk -v name="$(basename "$ARCHIVE")" '$2 != name && $2 != "*" name { print }' "$SUMS" > "$SUMS.tmp"
  mv "$SUMS.tmp" "$SUMS"
fi
(cd "$STAGE" && shasum -a 256 "$(basename "$ARCHIVE")" >> SHA256SUMS)
echo "Built $ARCHIVE"
