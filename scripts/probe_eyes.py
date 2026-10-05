#!/usr/bin/env python3
"""Arrival-day probe for the Reachy Eyes board (device check 8).

Opens the port the way the client does (exclusive, 115200, 50 ms write
timeout) and, by default, sends nothing: the README as summarised to us
documents no status or ping command. It logs whatever the unit says for
``--listen`` seconds. ``--send NAME`` writes one line from the client's
``WireProtocol`` table and nothing else can be sent. Every wire string is
UNVERIFIED (docs/dev/eyes-wire-protocol.md); this prints what the real unit
answers so the owner can settle the table.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "body"))

from maipai_body.bodies.reachy_mini.eyes_client import (  # noqa: E402
    DEFAULT_PROTOCOL,
    find_eyes_port,
    open_serial,
)


def main(argv: list[str] | None = None) -> int:
    commands = DEFAULT_PROTOCOL.named_commands()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="device path (default: find by USB ids 2e8a:10fc)")
    parser.add_argument("--listen", type=float, default=2.0, help="seconds to log replies")
    parser.add_argument(
        "--send",
        action="append",
        choices=sorted(commands),
        default=[],
        help="send one named table command (repeatable); default sends nothing",
    )
    args = parser.parse_args(argv)

    path = args.port or find_eyes_port()
    if path is None:
        print("no Reachy Eyes board found (check lsusb for 2e8a:10fc)", file=sys.stderr)
        return 1
    port = open_serial(path)
    print(f"opened {path} at {DEFAULT_PROTOCOL.baud} baud")
    try:
        for name in args.send:
            line = commands[name]
            port.write(DEFAULT_PROTOCOL.encode(line))
            print(f"sent {name}: {line!r}")
        deadline = time.monotonic() + args.listen
        while time.monotonic() < deadline:
            waiting = port.in_waiting
            if waiting:
                print(f"reply: {port.read(waiting)!r}")
            time.sleep(0.02)
    finally:
        port.close()
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
