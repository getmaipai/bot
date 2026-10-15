#!/bin/sh
set -eu
exec python3 - "$@" <<'PY'
import argparse
import ipaddress
import re
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Fail if a StackChan capture includes a destination other than the host.")
    parser.add_argument("capture", type=Path, help="text destination list or pcap/pcapng capture")
    parser.add_argument("host", help="the single permitted host IP address")
    args = parser.parse_args()
    try:
        host = ipaddress.ip_address(args.host)
        if not args.capture.is_file():
            raise ValueError(f"capture not found: {args.capture}")
        with args.capture.open("rb") as capture_handle:
            magic = capture_handle.read(4)
        is_pcap = magic in {
            b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4",
            b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d", b"\x0a\x0d\x0d\x0a",
        }
        if is_pcap:
            tshark = shutil.which("tshark")
            if not tshark:
                raise ValueError("tshark is required to inspect pcap/pcapng captures")
            result = subprocess.run(
                [tshark, "-n", "-r", str(args.capture), "-T", "fields", "-e", "ip.dst", "-e", "ipv6.dst"],
                capture_output=True, text=True, check=False,
            )
            if result.returncode:
                raise ValueError(result.stderr.strip() or "tshark could not read capture")
            raw = [value for value in result.stdout.split() if value]
        else:
            raw = []
            for line in args.capture.read_text(encoding="utf-8").splitlines():
                value = line.split("#", 1)[0].strip()
                if value:
                    raw.extend(re.findall(r"(?<![0-9A-Fa-f:.])(?:[0-9]{1,3}(?:\.[0-9]{1,3}){3}|[0-9A-Fa-f:]{3,})(?![0-9A-Fa-f:.])", value))
        try:
            destinations = {ipaddress.ip_address(value) for value in raw}
        except ValueError as exc:
            raise ValueError(f"invalid destination address in capture: {exc}") from exc
        if not destinations:
            raise ValueError("capture contains no destination addresses")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    other = sorted(destinations - {host}, key=str)
    if other:
        print("FAIL: destination(s) other than the host found:")
        for address in other:
            print(f"  {address}")
        return 1
    print(f"OK: all {len(destinations)} destination(s) match host {host}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
