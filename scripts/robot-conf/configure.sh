#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 3 ] || [ "$#" -gt 5 ]; then
  echo "usage: configure.sh <hub-ipv4> <router-ipv4> <robot-subnet> [tailnet-enabled] [nft-template]" >&2
  exit 2
fi
HUB="$1"
ROUTER="$2"
SUBNET="$3"
MAIPAI_TAILNET_ENABLED="${4:-0}"
NFT_TEMPLATE="${5:-$(dirname "$0")/maipai.nft}"
for ip in "$HUB" "$ROUTER"; do
  [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || { echo "invalid IPv4 address: $ip" >&2; exit 2; }
done
[[ "$SUBNET" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]|[1-2][0-9]|3[0-2])$ ]] || { echo "invalid IPv4 subnet: $SUBNET" >&2; exit 2; }
python3 - "$HUB" "$ROUTER" "$SUBNET" <<'PY'
import ipaddress
import sys
for value in sys.argv[1:3]:
    ipaddress.IPv4Address(value)
ipaddress.IPv4Network(sys.argv[3], strict=False)
PY
[[ "$MAIPAI_TAILNET_ENABLED" = 0 || "$MAIPAI_TAILNET_ENABLED" = 1 ]] || { echo "tailnet flag must be 0 or 1" >&2; exit 2; }

UNIT=/etc/systemd/system/reachy-mini-daemon.service.d/maipai.conf
install -d -m 0755 "$(dirname "$UNIT")"
cat > "$UNIT" <<'UNITFILE'
[Service]
ExecStart=
ExecStart=/venvs/apps_venv/bin/reachy-mini-daemon --dataset-update-interval 0 --no-preload-datasets --fastapi-host 127.0.0.1
Environment=HF_HUB_OFFLINE=1
Environment=MALLOC_ARENA_MAX=2
UnsetEnvironment=HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
UNITFILE
install -d -m 0755 /etc/nftables.d
TAILNET_RULE='# tailnet is disabled'
if [ "$MAIPAI_TAILNET_ENABLED" = 1 ]; then
  TAILNET_RULE='oifname "tailscale0" accept'
fi
sed -e "s/HUB_ADDRESS/$HUB/g" -e "s/ROUTER_ADDRESS/$ROUTER/g" -e "s|TAILNET_RULE|$TAILNET_RULE|" "$NFT_TEMPLATE" > /etc/nftables.d/maipai.nft
cat > /etc/nftables.conf <<'NFT'
#!/usr/sbin/nft -f
flush ruleset
include "/etc/nftables.d/*.nft"
NFT
systemctl mask --now systemd-timesyncd.service apt-daily.timer apt-daily-upgrade.timer
systemctl enable --now nftables.service
systemctl daemon-reload
systemctl restart reachy-mini-daemon.service

# Read back every installed setting. The operator's application remains
# local-only on the robot and the daemon remains pinned to the unit above.
grep -q -- '--dataset-update-interval 0 --no-preload-datasets --fastapi-host 127.0.0.1' "$UNIT"
grep -qx 'Environment=HF_HUB_OFFLINE=1' "$UNIT"
grep -qx 'Environment=MALLOC_ARENA_MAX=2' "$UNIT"
! grep -Eqi '^(Environment=)?(HTTP|HTTPS|ALL)_PROXY=' "$UNIT"
grep -q "elements = { $HUB }" /etc/nftables.d/maipai.nft
test "$(systemctl is-enabled systemd-timesyncd.service)" = masked
test "$(systemctl is-enabled apt-daily.timer)" = masked
test "$(systemctl is-enabled apt-daily-upgrade.timer)" = masked
systemctl is-active --quiet nftables.service
nft list table inet maipai >/dev/null
EOF
