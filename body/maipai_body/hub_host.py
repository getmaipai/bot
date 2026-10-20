"""Host launcher for a self-contained MaiPai Bot hub sidecar.

The Home design names voice and avatar ports; the vision port is the third
listener and Home part B allocates it with the same per-device policy.
"""

from __future__ import annotations

import argparse
import errno
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"port {value!r} is not an integer; choose 1..65535"
        ) from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(
            f"port {port} is outside 1..65535; choose a valid TCP port"
        )
    return port


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maipai-bot-host")
    subs = parser.add_subparsers(dest="command", required=True)
    run = subs.add_parser("run", help="run the StackChan app as a hub sidecar")
    run.add_argument("--data-dir", required=True, type=Path)
    run.add_argument("--hub-url", required=True)
    run.add_argument("--voice-port", required=True, type=_port)
    run.add_argument("--avatar-port", required=True, type=_port)
    run.add_argument("--vision-port", type=_port)
    run.add_argument("--label", default="StackChan")
    provision = subs.add_parser("provision", help="provision a StackChan")
    provision.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def _check_data_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".maipai-bot-write-check"
        probe.touch(exist_ok=True)
        probe.unlink()
    except OSError as exc:
        raise ValueError(
            f"data directory {path} is not writable; choose a writable --data-dir"
        ) from exc


def _check_port(port: int) -> None:
    sock = socket.socket()
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, 48, 98, 10048):
            raise OSError(
                75,
                f"Port {port} is in use by another program. Home will show this in Repairs.",
            ) from exc
        raise
    finally:
        sock.close()


def _runtime_environment(args: argparse.Namespace) -> dict[str, str]:
    vision_port = args.vision_port or 0
    return {
        "MAIPAI_BODY": "stackchan",
        "MAIPAI_HUB_HOST": "1",
        "MAIPAI_BOT_DATA_DIR": str(args.data_dir),
        "MAIPAI_XIAOZHI_HOST": "0.0.0.0",
        "MAIPAI_XIAOZHI_PORT": str(args.voice_port),
        "MAIPAI_STACKCHAN_AVATAR_HOST": "0.0.0.0",
        "MAIPAI_STACKCHAN_AVATAR_PORT": str(args.avatar_port),
        "MAIPAI_VISION_HOST": "0.0.0.0",
        "MAIPAI_VISION_PORT": str(vision_port),
        "MAIPAI_HUB_URL": args.hub_url,
        "MAIPAI_BOT_LABEL": args.label,
    }


def main() -> int:
    args = _parser().parse_args()
    if args.command == "provision":
        from maipai_body.bodies.stackchan.xiaozhi.provision import main as provision_main

        return provision_main(args.args if args.args else None)
    if not args.hub_url.strip():
        print("hub URL is missing; provide --hub-url URL", file=sys.stderr)
        return 2
    parsed_hub = urlparse(args.hub_url)
    if parsed_hub.scheme not in {"http", "https"} or not parsed_hub.hostname:
        print("hub URL is invalid; provide an http:// or https:// hub address", file=sys.stderr)
        return 2
    try:
        _check_data_dir(args.data_dir)
        ports = [args.voice_port, args.avatar_port]
        if args.vision_port is not None:
            ports.append(args.vision_port)
        if len(ports) != len(set(ports)):
            raise ValueError(
                "listener ports must be different; choose a distinct TCP port for each"
            )
        for port in ports:
            _check_port(port)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        if exc.errno == 75:
            print(str(exc.args[1]), file=sys.stderr)
            return 75
        print(f"cannot check listener port: {exc}", file=sys.stderr)
        return 2
    os.environ.update(_runtime_environment(args))
    os.execv(sys.executable, [sys.executable, "-m", "maipai_body.app"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
