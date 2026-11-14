#!/usr/bin/env python3
"""Trip relay for the StackChan: runs on the owner's laptop, exposes nothing to the internet.

The robot joins the laptop's own Wi-Fi (macOS Internet Sharing: iPhone USB tethering shared to Wi-Fi; the laptop is the
gateway of that network, usually 192.168.2.1). The robot's firmware tries the saved home address first, then the gateway
of the network it is on, then 192.168.2.1, on the same ports. This program listens on those ports and passes each connection
byte for byte to the Studio over Tailscale. It never reads, stores or prints the stream (the robot's pairing token travels
inside it): only counts are printed.

  python3 trip_relay.py            # find the sharing address, listen, forward to the Studio
  python3 trip_relay.py --check    # only test that the Studio's two ports answer over Tailscale
  python3 trip_relay.py --doctor   # print this laptop's addresses and what the robot should see

Options: --bind ADDR (default: the sharing address found on bridge100, else 0.0.0.0), --target HOST, --ports A,B.
Needs only python3 (standard library) and Tailscale signed in on the laptop.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import asyncio
import re
import socket
import subprocess
import sys
import time

DEFAULT_PORTS = (
    62923,
    62924,
)  # the robot's voice and avatar services on the Studio (hub log: "listening on ws://0.0.0.0:...")
DEFAULT_TARGET = "jesses-mac-studio-2.cow-tint.ts.net"
SHARING_INTERFACES = ("bridge100", "bridge101", "bridge102")
IDLE_TIMEOUT_S = 600  # a half-open connection (the robot vanished without closing) is dropped after ten quiet minutes
SSID_REMINDER = (
    "Name the Internet Sharing Wi-Fi network starting with 'maipai' (for example 'maipai-trip') and give it a WPA2 password: "
    "the robot only uses this relay on a network whose name starts with 'maipai'."
)


def parse_ifconfig(text: str) -> dict[str, list[str]]:
    """interface name -> its IPv4 addresses, from `ifconfig` output."""
    result: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+):", line)
        if match:
            current = match.group(1)
            result.setdefault(current, [])
            continue
        inet = re.match(r"^\s+inet (\d+\.\d+\.\d+\.\d+) ", line)
        if inet and current:
            result[current].append(inet.group(1))
    return result


def read_interfaces() -> dict[str, list[str]]:
    try:
        out = subprocess.run(["/sbin/ifconfig"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_ifconfig(out)


def sharing_address(interfaces: dict[str, list[str]]) -> str | None:
    """The address the robot will see as its gateway: the laptop's own sharing bridge."""
    for name in SHARING_INTERFACES:
        if interfaces.get(name):
            return interfaces[name][0]
    return None


class Counters:
    def __init__(self) -> None:
        self.connections = 0
        self.active = 0
        self.to_hub = 0
        self.from_hub = 0
        self.failed = 0


async def _pipe(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, counters: Counters, attr: str
) -> None:
    try:
        while True:
            data = await asyncio.wait_for(reader.read(65536), IDLE_TIMEOUT_S)
            if not data:
                break
            setattr(counters, attr, getattr(counters, attr) + len(data))
            writer.write(data)
            await writer.drain()
    except (ConnectionError, TimeoutError, asyncio.CancelledError, OSError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def _keepalive(writer: asyncio.StreamWriter) -> None:
    sock = writer.get_extra_info("socket")
    if sock is not None:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass


def make_handler(target: str, port: int, counters: Counters, say):
    async def handle(
        local_reader: asyncio.StreamReader, local_writer: asyncio.StreamWriter
    ) -> None:
        peer = local_writer.get_extra_info("peername")
        who = peer[0] if peer else "robot"
        counters.connections += 1
        try:
            remote_reader, remote_writer = await asyncio.wait_for(
                asyncio.open_connection(target, port), 8
            )
        except Exception as error:  # the Studio is not reachable: tell the person what to do, drop the robot's connection
            counters.failed += 1
            say(
                f"port {port}: the Studio did not answer ({error.__class__.__name__}). Is Tailscale on and signed in?"
            )
            local_writer.close()
            return
        _keepalive(local_writer)
        _keepalive(remote_writer)
        counters.active += 1
        say(f"robot connected from {who} to port {port} (open now: {counters.active})")
        try:
            await asyncio.gather(
                _pipe(local_reader, remote_writer, counters, "to_hub"),
                _pipe(remote_reader, local_writer, counters, "from_hub"),
            )
        finally:
            counters.active -= 1
            say(f"robot connection on port {port} closed (open now: {counters.active})")

    return handle


async def serve(
    bind: str,
    ports: tuple[int, ...],
    target: str,
    say=print,
    stop: asyncio.Event | None = None,
    counters: Counters | None = None,
    status_every_s: float = 30.0,
):
    """Listen on every port and relay; returns when `stop` is set (a test) or never. Returns the servers' bound ports."""
    counters = counters or Counters()
    servers = []
    for port in ports:
        servers.append(
            await asyncio.start_server(
                make_handler(target, port, counters, say), bind, port, reuse_address=True
            )
        )
    bound = tuple(s.sockets[0].getsockname()[1] for s in servers)
    say(f"relaying {bind} {bound} -> {target} {ports}. Waiting for the robot. Ctrl-C to stop.")
    last = 0.0
    try:
        while stop is None or not stop.is_set():
            await asyncio.sleep(0.2 if stop is not None else 1.0)
            now = time.monotonic()
            if now - last >= status_every_s:
                last = now
                state = "robot connected" if counters.active else "waiting for the robot"
                say(
                    f"{state}; connections so far {counters.connections}; bytes to the Studio {counters.to_hub}, from it {counters.from_hub}"
                )
    finally:
        for server in servers:
            server.close()
    return bound


def check(target: str, ports: tuple[int, ...]) -> bool:
    ok = True
    for port in ports:
        try:
            socket.create_connection((target, port), timeout=6).close()
            print(f"OK    {target}:{port} answers")
        except OSError as error:
            ok = False
            print(
                f"FAIL  {target}:{port} ({error.__class__.__name__}). Turn Tailscale on and try again."
            )
    return ok


def doctor(target: str, ports: tuple[int, ...]) -> int:
    interfaces = read_interfaces()
    print("This laptop's addresses:")
    for name, addrs in sorted(interfaces.items()):
        if addrs and not name.startswith(("lo", "utun", "awdl", "llw", "gif", "stf")):
            print(f"  {name}: {', '.join(addrs)}")
    address = sharing_address(interfaces)
    if address:
        print(
            f"\nInternet Sharing is on. The robot will see this laptop as {address}; the relay will listen there."
        )
    else:
        print(
            "\nInternet Sharing is not on yet (no bridge100). Turn it on (System Settings > General > Sharing > Internet Sharing,"
        )
        print("share the iPhone USB connection to Wi-Fi), then run this again.")
    print("\n" + SSID_REMINDER)
    print("\nThe Studio over Tailscale:")
    return 0 if check(target, ports) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--bind", default=None)
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--ports", default=",".join(str(p) for p in DEFAULT_PORTS))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    args = parser.parse_args(argv)
    ports = tuple(int(p) for p in args.ports.split(",") if p.strip())
    if args.check:
        return 0 if check(args.target, ports) else 1
    if args.doctor:
        return doctor(args.target, ports)
    bind = args.bind
    if bind is None:
        bind = sharing_address(read_interfaces())
        if bind is None:
            print(
                "Internet Sharing is not on, so there is no laptop network for the robot yet. Turn it on and run this again."
            )
            print("(To test at home without it, run with --bind 0.0.0.0.)")
            print(SSID_REMINDER)
            return 1
    try:
        asyncio.run(serve(bind, ports, args.target))
    except OSError as error:
        print(
            f"cannot listen on {bind}:{ports} ({error}). Another copy may be running; stop it and try again."
        )
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
