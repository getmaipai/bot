#!/bin/sh
set -eu
exec python3 - "$@" <<'PY'
import argparse
import ipaddress
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Reject StackChan captures with destinations outside the local allowlist."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pcap", type=Path, help="pcap or pcapng file (requires tshark)")
    source.add_argument("--hosts", type=Path, help="text file with one destination IP per line")
    parser.add_argument("--hub", action="append", required=True, help="allowed hub IP (repeatable)")
    parser.add_argument(
        "--router", action="append", required=True, help="allowed router IP for local DNS/DHCP"
    )
    return parser.parse_args()


def read_hosts(args):
    if args.hosts:
        if not args.hosts.is_file():
            raise ValueError(f"Host list not found: {args.hosts}. Pass a readable capture list.")
        lines = args.hosts.read_text(encoding="utf-8").splitlines()
        values = [line.split("#", 1)[0].strip() for line in lines]
    else:
        if not args.pcap.is_file():
            raise ValueError(f"Capture not found: {args.pcap}. Pass a readable pcap or pcapng file.")
        tshark = shutil.which("tshark")
        if not tshark:
            raise ValueError("tshark is required to read pcap files. Install Wireshark or pass --hosts.")
        result = subprocess.run(
            [tshark, "-n", "-r", str(args.pcap), "-T", "fields", "-e", "ip.dst", "-e", "ipv6.dst"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            detail = result.stderr.strip() or f"tshark exited {result.returncode}"
            raise ValueError(f"Could not read capture: {detail}. Check the file and retry.")
        values = [field.strip() for row in result.stdout.splitlines() for field in row.split("\t")]

    hosts = set()
    for value in values:
        if not value:
            continue
        try:
            hosts.add(ipaddress.ip_address(value))
        except ValueError as exc:
            raise ValueError(
                f"Invalid destination {value!r}. Use numeric IPv4 or IPv6 addresses in the capture list."
            ) from exc
    if not hosts:
        raise ValueError("The capture contains no destination IPs. Supply a non-empty capture and retry.")
    return hosts


def main():
    args = parse_args()
    try:
        destinations = read_hosts(args)
        exact = {ipaddress.ip_address(value) for value in args.hub + args.router}
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    tailscale = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
    mdns = {ipaddress.ip_address("224.0.0.251"), ipaddress.ip_address("ff02::fb")}
    dhcp = {ipaddress.ip_address("255.255.255.255"), ipaddress.ip_address("ff02::1:2")}

    def allowed(address):
        return address in exact or address in mdns or address in dhcp or any(
            address.version == network.version and address in network for network in tailscale
        )

    rejected = sorted((address for address in destinations if not allowed(address)), key=str)
    if rejected:
        print("FAIL: third-party destination(s) found:")
        for address in rejected:
            print(f"  {address}")
        print("Remove the outbound contact or add a documented local destination, then capture again.")
        return 1
    print(f"OK: {len(destinations)} unique destination(s) fit the local StackChan allowlist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
