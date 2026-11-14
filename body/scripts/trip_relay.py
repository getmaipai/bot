#!/usr/bin/env python3
"""Trip relay v2 for the StackChan: runs on the owner's laptop, exposes nothing to the internet.

The robot joins the laptop's own Wi-Fi (macOS Internet Sharing: iPhone USB tethering shared to Wi-Fi; the laptop is the
gateway of that network, usually 192.168.2.1). The robot's firmware tries the saved home address first, then the gateway
of the network it is on, then 192.168.2.1, on the same ports. This program listens on those ports and passes each connection
byte for byte to the Studio over Tailscale. It never reads, stores or prints the stream (the robot's pairing token travels
inside it): only counts are printed or logged.

  python3 trip_relay.py            # the default: wait for Internet Sharing, relay, heal itself, show a status page
  python3 trip_relay.py --doctor   # plain-English checks and what to do about each one
  python3 trip_relay.py --check    # only test that the Studio's two ports answer over Tailscale
  python3 trip_relay.py --no-wait  # v1 behaviour: refuse to start if Internet Sharing is not on

Self-healing: it waits for Internet Sharing to appear, restarts its listeners if they stop or the sharing address changes,
retries the Studio with a short pause, and notices when the laptop wakes from sleep. macOS notifications (rate limited) tell you
when the robot connects or is lost, when the Studio cannot be reached, and when Tailscale or Internet Sharing is off.
Status page: http://127.0.0.1:8899 on this laptop (big lights and the next step in plain words). Log: ~/Library/Logs/maipai-trip-relay.log
(no tokens, no stream contents).

Options: --bind ADDR, --target HOST, --ports A,B, --status-port N, --no-status, --status-on-sharing (also serve the status page on the
laptop's private sharing network, for the robot's own Wi-Fi only), --no-notify, --log PATH, --no-log.
Needs only python3 (standard library) and Tailscale signed in on the laptop.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from html import escape
from pathlib import Path

VERSION = "2"
DEFAULT_PORTS = (
    62923,
    62924,
)  # the robot's voice and avatar services on the Studio (hub log: "listening on ws://0.0.0.0:...")
DEFAULT_TARGET = "jesses-mac-studio-2.cow-tint.ts.net"
SHARING_INTERFACES = ("bridge100", "bridge101", "bridge102")
IDLE_TIMEOUT_S = 600  # a half-open connection (the robot vanished without closing) is dropped after ten quiet minutes
STATUS_PORT = 8899
TICK_S = 2.0
PROBE_EVERY_S = 10.0
PROBE_FAST_EVERY_S = 3.0
TAILSCALE_EVERY_S = 20.0
ROBOT_LOST_AFTER_S = 20.0  # a robot that reconnects inside this is not "lost"
NOTIFY_GAP_S = 60.0
LOG_PATH = Path.home() / "Library" / "Logs" / "maipai-trip-relay.log"
LOG_MAX_BYTES = 1_000_000
TAILSCALE_CLI = (
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    "/usr/local/bin/tailscale",
    "/opt/homebrew/bin/tailscale",
)
SSID_REMINDER = (
    "Name the Internet Sharing Wi-Fi network starting with 'maipai' (for example 'maipai-trip') and give it a WPA2 password: "
    "the robot only uses this relay on a network whose name starts with 'maipai'."
)


# ---- the laptop's network ----


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


def tailscale_state(run: Callable = subprocess.run) -> str:
    """'on' when Tailscale is running and signed in, 'off' when it is not, 'unknown' when no command-line tool is found."""
    for path in TAILSCALE_CLI:
        if not os.path.exists(path):
            continue
        try:
            done = run([path, "status", "--json"], capture_output=True, text=True, timeout=6)
            data = json.loads(done.stdout or "{}")
            return "on" if data.get("BackendState") == "Running" else "off"
        except (OSError, subprocess.SubprocessError, ValueError):
            return "off"
    return "unknown"


def sharing_network_name(run: Callable = subprocess.run) -> str | None:
    """The Wi-Fi network name Internet Sharing uses, when macOS lets this read it (not always)."""
    try:
        done = run(
            ["/usr/bin/defaults", "read", "/Library/Preferences/SystemConfiguration/com.apple.nat"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'NetworkName\s*=\s*"?([^";\n]+)"?\s*;', done.stdout or "")
    return match.group(1).strip() if match else None


# ---- counts, notifications, log ----


class Counters:
    def __init__(self) -> None:
        self.connections = 0
        self.active = 0
        self.to_hub = 0
        self.from_hub = 0
        self.failed = 0
        self.by_port_active: dict[int, int] = {}
        self.last_robot_at: float | None = (
            None  # wall clock of the last time a robot connection was open
        )


class Notifier:
    """macOS notifications through osascript, at most one per kind per minute; text is a fixed sentence, never the stream."""

    def __init__(
        self,
        enabled: bool = True,
        run: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        gap_s: float = NOTIFY_GAP_S,
    ) -> None:
        self.enabled = enabled
        self._run = run or self._osascript
        self._clock = clock
        self._gap = gap_s
        self._last: dict[str, float] = {}

    @staticmethod
    def _osascript(text: str) -> None:
        safe = text.replace("\\", " ").replace('"', " ")
        try:
            subprocess.Popen(
                [
                    "/usr/bin/osascript",
                    "-e",
                    f'display notification "{safe}" with title "MaiPai trip relay"',
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass

    def notify(self, key: str, text: str) -> bool:
        if not self.enabled:
            return False
        now = self._clock()
        if key in self._last and now - self._last[key] < self._gap:
            return False
        self._last[key] = now
        self._run(text)
        return True


class FileLog:
    """A say() that prints and appends to a log file (capped: the file restarts when it passes one megabyte)."""

    def __init__(
        self, path: Path | None, out: Callable[[str], None] = print, max_bytes: int = LOG_MAX_BYTES
    ) -> None:
        self.path = path
        self._out = out
        self._max = max_bytes

    def __call__(self, line: str) -> None:
        self._out(line)
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > self._max:
                self.path.write_text("")
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
        except OSError:
            pass


# ---- relaying ----


async def _pipe(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, counters: Counters, attr: str
) -> None:
    try:
        while True:
            data = await asyncio.wait_for(reader.read(65536), IDLE_TIMEOUT_S)
            if not data:
                break
            setattr(counters, attr, getattr(counters, attr) + len(data))
            counters.last_robot_at = time.time()
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
        counters.by_port_active[port] = counters.by_port_active.get(port, 0) + 1
        counters.last_robot_at = time.time()
        say(f"robot connected from {who} to port {port} (open now: {counters.active})")
        try:
            await asyncio.gather(
                _pipe(local_reader, remote_writer, counters, "to_hub"),
                _pipe(remote_reader, local_writer, counters, "from_hub"),
            )
        finally:
            counters.active -= 1
            counters.by_port_active[port] = max(0, counters.by_port_active.get(port, 1) - 1)
            counters.last_robot_at = time.time()
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
    """v1 entry kept for the tests and --no-wait: listen on every port and relay until `stop` is set or forever."""
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


# ---- the Studio check ----


async def probe_studio(
    target: str, ports: tuple[int, ...], timeout: float = 4.0
) -> dict[int, bool]:
    result: dict[int, bool] = {}
    for port in ports:
        try:
            _reader, writer = await asyncio.wait_for(asyncio.open_connection(target, port), timeout)
            writer.close()
            result[port] = True
        except (OSError, TimeoutError, asyncio.TimeoutError):  # noqa: UP041
            result[port] = False
    return result


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


# ---- the status the page and the notifications use ----


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} seconds ago"
    if seconds < 3600:
        return f"{seconds // 60} minutes ago"
    return f"{seconds // 3600} hours ago"


def build_status(
    *,
    sharing: str | None,
    tailscale: str,
    studio: dict[int, bool] | None,
    ports: tuple[int, ...],
    counters: Counters,
    now_wall: float,
    listening: bool,
    bind_failed: bool = False,
) -> dict:
    voice_port, avatar_port = ports[0], ports[-1]
    studio = studio or {}
    studio_ok = bool(studio) and all(studio.get(p) for p in ports)
    studio_known = bool(studio)
    voice_up = counters.by_port_active.get(voice_port, 0) > 0
    avatar_up = counters.by_port_active.get(avatar_port, 0) > 0
    robot_ok = voice_up and avatar_up
    last_seen = (
        _ago(now_wall - counters.last_robot_at) if counters.last_robot_at is not None else "not yet"
    )
    lights = [
        {
            "key": "sharing",
            "label": "Internet Sharing (the laptop's own Wi-Fi)",
            "state": "ok" if sharing else "bad",
            "detail": f"on, the robot will see this laptop as {sharing}" if sharing else "off",
        },
        {
            "key": "tailscale",
            "label": "Tailscale on this laptop",
            "state": {"on": "ok", "off": "bad"}.get(tailscale, "wait"),
            "detail": {"on": "signed in and running", "off": "off or signed out"}.get(
                tailscale, "could not be checked (the Studio test below tells the truth)"
            ),
        },
        {
            "key": "studio",
            "label": "The Studio (your home hub)",
            "state": "wait" if not studio_known else ("ok" if studio_ok else "bad"),
            "detail": "checking"
            if not studio_known
            else (
                "answers on both ports"
                if studio_ok
                else f"voice {'ok' if studio.get(voice_port) else 'not answering'}, avatar {'ok' if studio.get(avatar_port) else 'not answering'}"
            ),
        },
        {
            "key": "robot",
            "label": "The robot",
            "state": "ok" if robot_ok else ("wait" if (voice_up or avatar_up) else "bad"),
            "detail": (
                "connected (voice and avatar)"
                if robot_ok
                else (
                    f"half connected (voice {'yes' if voice_up else 'no'}, avatar {'yes' if avatar_up else 'no'})"
                    if (voice_up or avatar_up)
                    else f"not connected; last seen {last_seen}"
                )
            ),
        },
    ]
    if not sharing:
        headline = "Waiting for Internet Sharing"
        next_step = "Plug in the iPhone, then on this laptop open System Settings > General > Sharing > Internet Sharing: share the iPhone USB connection to Wi-Fi, name the network starting with maipai (for example maipai-trip), set a WPA2 password and turn it on."
    elif tailscale == "off":
        headline = "Tailscale is off"
        next_step = (
            "Turn Tailscale on in the menu bar and sign in. The relay keeps trying by itself."
        )
    elif studio_known and not studio_ok:
        headline = "The Studio is not answering"
        next_step = "Check that Tailscale is on here and that the Studio at home is on and online. The relay tries again every few seconds."
    elif bind_failed and not listening:
        headline = "The relay cannot start"
        next_step = "Another copy of the relay may already be running (look for another Terminal window and close it), or something else is using the robot's ports. I keep trying by myself every few seconds."
    elif not listening:
        headline = "Getting ready"
        next_step = "Starting the relay. This takes a moment."
    elif not robot_ok:
        headline = "Waiting for the robot"
        next_step = f"Make sure the robot joined the Wi-Fi network that starts with maipai. If it has not connected after a minute, switch the robot off and on, then wait up to a minute. Last seen: {last_seen}."
    else:
        headline = "All good: the robot is connected through your laptop"
        next_step = "Nothing to do. Leave this window open."
    return {
        "version": VERSION,
        "headline": headline,
        "ok": bool(sharing) and studio_ok and robot_ok,
        "lights": lights,
        "next_step": next_step,
        "robot_last_seen": last_seen,
        "connections": counters.connections,
        "bytes_to_studio": counters.to_hub,
        "bytes_from_studio": counters.from_hub,
    }


_LIGHT_COLOURS = {"ok": "#1a9c4a", "bad": "#d93636", "wait": "#9aa0a6"}


def render_html(status: dict) -> str:
    rows = []
    for light in status["lights"]:
        colour = _LIGHT_COLOURS.get(light["state"], "#9aa0a6")
        rows.append(
            f'<div class="row"><span class="dot" style="background:{colour}"></span>'
            f'<div><div class="label">{escape(light["label"])}</div><div class="detail">{escape(light["detail"])}</div></div></div>'
        )
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<meta http-equiv=refresh content=3><title>MaiPai trip relay</title>"
        "<style>body{font-family:-apple-system,system-ui,sans-serif;margin:24px;max-width:720px;color:#1b1b1b;background:#fff}"
        "@media(prefers-color-scheme:dark){body{color:#eee;background:#161616}}"
        "h1{font-size:28px;margin:0 0 16px}.row{display:flex;gap:16px;align-items:center;margin:14px 0}"
        ".dot{width:34px;height:34px;border-radius:50%;flex:none}.label{font-size:22px;font-weight:600}"
        ".detail{font-size:18px;opacity:.8}.next{font-size:20px;margin:24px 0;padding:16px;border:2px solid #888;border-radius:12px}"
        ".small{font-size:15px;opacity:.7}</style></head><body>"
        f"<h1>{escape(status['headline'])}</h1>"
        + "".join(rows)
        + f"<div class=next><b>What to do:</b> {escape(status['next_step'])}</div>"
        f"<div class=small>Connections so far {status['connections']}. Bytes to the Studio {status['bytes_to_studio']}, from it {status['bytes_from_studio']}. "
        f"This page refreshes by itself. Relay version {escape(status['version'])}.</div></body></html>"
    )


async def serve_status(
    get_status: Callable[[], dict], bind: str, port: int, allowed_hosts: set[str]
):
    """A tiny read-only status page. Only GET /, /index and /status.json; any other Host header is refused (DNS rebinding)."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, OSError):
            writer.close()
            return
        lines = head.decode("latin-1", "replace").split("\r\n")
        parts = lines[0].split(" ")
        host = ""
        for line in lines[1:]:
            if line.lower().startswith("host:"):
                host = line.split(":", 1)[1].strip()
        host_only = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        if len(parts) < 2 or parts[0] != "GET":
            body, status_line, kind = (
                b"Only GET is supported.",
                "405 Method Not Allowed",
                "text/plain",
            )
        elif host_only not in allowed_hosts:
            body, status_line, kind = (
                b"Open this page by its own address.",
                "400 Bad Request",
                "text/plain",
            )
        elif parts[1].split("?")[0] in ("/", "/index", "/index.html"):
            body, status_line, kind = (
                render_html(get_status()).encode(),
                "200 OK",
                "text/html; charset=utf-8",
            )
        elif parts[1].split("?")[0] == "/status.json":
            body, status_line, kind = (
                json.dumps(get_status()).encode(),
                "200 OK",
                "application/json",
            )
        else:
            body, status_line, kind = b"Not found.", "404 Not Found", "text/plain"
        writer.write(
            f"HTTP/1.0 {status_line}\r\nContent-Type: {kind}\r\nContent-Length: {len(body)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        try:
            await writer.drain()
        finally:
            writer.close()

    return await asyncio.start_server(handle, bind, port, reuse_address=True)


# ---- the supervisor: never gives up ----


class Supervisor:
    def __init__(
        self,
        *,
        target: str = DEFAULT_TARGET,
        ports: tuple[int, ...] = DEFAULT_PORTS,
        listen_ports: tuple[int, ...] | None = None,
        say: Callable[[str], None] = print,
        notifier: Notifier | None = None,
        interfaces: Callable[[], dict[str, list[str]]] = read_interfaces,
        probe: Callable = probe_studio,
        tailscale: Callable[[], str] = tailscale_state,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        status_port: int | None = STATUS_PORT,
        status_on_sharing: bool = False,
        bind_override: str | None = None,
    ) -> None:
        self.target = target
        self.ports = ports
        self.listen_ports = listen_ports or ports
        self.say = say
        self.notifier = notifier or Notifier(enabled=False)
        self._interfaces = interfaces
        self._probe = probe
        self._tailscale = tailscale
        self._clock = clock
        self._wall = wall
        self.status_port = status_port
        self.status_on_sharing = status_on_sharing
        self.bind_override = bind_override
        self.counters = Counters()
        self.servers: list[asyncio.AbstractServer] = []
        self.status_servers: list[asyncio.AbstractServer] = []
        self.bound_to: str | None = None
        self.bound_ports: tuple[int, ...] = ()
        self.sharing: str | None = None
        self.tailscale_now = "unknown"
        self.studio: dict[int, bool] = {}
        self._next_probe = float("-inf")
        self._next_tailscale = float("-inf")
        self._bind_failures = 0
        self._next_bind = float("-inf")
        self._robot_up = False
        self._robot_down_since: float | None = None
        self._studio_ok: bool | None = None
        self._tailscale_last: str | None = None
        self._sharing_last: bool | None = None

    # ---- what the page shows ----

    def status(self) -> dict:
        return build_status(
            sharing=self.sharing,
            tailscale=self.tailscale_now,
            studio=self.studio,
            ports=self.ports,
            counters=self.counters,
            now_wall=self._wall(),
            listening=bool(self.servers),
            bind_failed=self._bind_failures > 0,
        )

    # ---- listeners ----

    async def _stop_listeners(self) -> None:
        for server in self.servers:
            server.close()
        for server in self.servers:
            try:
                await asyncio.wait_for(server.wait_closed(), 2)
            except (TimeoutError, asyncio.TimeoutError, OSError):  # noqa: UP041  (python 3.9 on the laptop: they differ)
                pass
        self.servers = []
        self.bound_to = None

    async def _start_listeners(self, address: str) -> bool:
        try:
            servers = []
            for listen_port, target_port in zip(self.listen_ports, self.ports):  # noqa: B905  (python 3.9 on the laptop has no strict=)
                servers.append(
                    await asyncio.start_server(
                        make_handler(self.target, target_port, self.counters, self.say),
                        address,
                        listen_port,
                        reuse_address=True,
                    )
                )
        except OSError as error:
            for server in locals().get("servers", []):
                server.close()
            self._bind_failures += 1
            self._next_bind = self._clock() + min(30.0, 2.0 * self._bind_failures)
            self.say(
                f"cannot listen on {address} ({error}). Another copy of this relay may be running; I will try again."
            )
            return False
        self.servers = servers
        self.bound_to = address
        self.bound_ports = tuple(s.sockets[0].getsockname()[1] for s in servers)
        self._bind_failures = 0
        self.say(
            f"relaying {address} {self.bound_ports} -> {self.target} {self.ports}. Waiting for the robot."
        )
        return True

    async def _start_status(self, sharing: str | None) -> None:
        if self.status_port is None:
            return
        hosts = {"127.0.0.1", "localhost", "[::1]"}
        binds = ["127.0.0.1"]
        if self.status_on_sharing and sharing:
            binds.append(sharing)
            hosts.add(sharing)
        for bind in binds:
            try:
                self.status_servers.append(
                    await serve_status(self.status, bind, self.status_port, hosts)
                )
                self.say(f"status page: http://{bind}:{self.status_port}")
            except OSError as error:
                self.say(
                    f"the status page could not start on {bind}:{self.status_port} ({error}); the relay still works."
                )

    # ---- one pass ----

    async def tick(self, slept_s: float = TICK_S) -> None:
        now = self._clock()
        # sleep and wake: a pass that comes much later than planned means the laptop slept
        if slept_s > TICK_S * 3 + 20:
            self.say(
                f"The laptop woke up after about {int(slept_s)} seconds asleep. Checking everything again."
            )
            self._next_probe = float("-inf")
            self._next_tailscale = float("-inf")
            await self._stop_listeners()
        addr = self.bind_override or sharing_address(self._interfaces())
        had_sharing = self._sharing_last
        self.sharing = addr
        if (addr is not None) != had_sharing:
            self._sharing_last = addr is not None
            if addr is None and had_sharing is not None:
                self.say(
                    "Internet Sharing went off. Turn it back on; I will start again by myself."
                )
                self.notifier.notify(
                    "sharing", "Internet Sharing is off. Turn it back on for the robot."
                )
            elif addr is not None:
                self.say(f"Internet Sharing is on; the robot will see this laptop as {addr}.")
        if addr != self.bound_to and self.servers:
            await self._stop_listeners()
        if addr is not None and not self.servers and now >= self._next_bind:
            await self._start_listeners(addr)
        elif self.servers and any(not s.is_serving() for s in self.servers):
            self.say("A listener stopped by itself. Restarting it.")
            await self._stop_listeners()
        # Tailscale
        if now >= self._next_tailscale:
            self._next_tailscale = now + TAILSCALE_EVERY_S
            loop = asyncio.get_running_loop()
            self.tailscale_now = await loop.run_in_executor(None, self._tailscale)
            if self.tailscale_now != self._tailscale_last:
                if self.tailscale_now == "off" and self._tailscale_last is not None:
                    self.say("Tailscale is off. Turn it on in the menu bar.")
                    self.notifier.notify(
                        "tailscale", "Tailscale is off on this laptop. Turn it on."
                    )
                self._tailscale_last = self.tailscale_now
        # the Studio
        if now >= self._next_probe:
            self.studio = await self._probe(self.target, self.ports)
            ok = all(self.studio.get(p) for p in self.ports)
            self._next_probe = now + (PROBE_EVERY_S if ok else PROBE_FAST_EVERY_S)
            if ok != self._studio_ok:
                if not ok:
                    self.say(
                        "The Studio is not answering. Is Tailscale on here, and is the Studio on?"
                    )
                    if self._studio_ok is not None or self.servers:
                        self.notifier.notify(
                            "studio", "The Studio is not reachable. Check Tailscale."
                        )
                elif self._studio_ok is False:
                    self.say("The Studio answers again.")
                self._studio_ok = ok
        # the robot
        up = self.counters.active > 0
        if up and not self._robot_up:
            self._robot_up = True
            self._robot_down_since = None
            self.notifier.notify("robot_up", "The robot is connected through your laptop.")
        elif not up and self._robot_up:
            if self._robot_down_since is None:
                self._robot_down_since = now
            elif now - self._robot_down_since >= ROBOT_LOST_AFTER_S:
                self._robot_up = False
                self.say(
                    "The robot connection is lost. It should reconnect by itself within a minute."
                )
                self.notifier.notify(
                    "robot_lost", "The robot connection was lost. It should reconnect by itself."
                )
        elif up:
            self._robot_down_since = None

    async def run(self, stop: asyncio.Event | None = None, tick_s: float = TICK_S) -> None:
        await self._start_status(None)
        last = self._wall()
        try:
            while stop is None or not stop.is_set():
                now_wall = self._wall()
                gap = now_wall - last
                last = now_wall
                try:
                    await self.tick(gap if gap > tick_s else tick_s)
                except Exception as error:  # nothing may stop the relay: say it and go on
                    self.say(f"internal problem ({error.__class__.__name__}); carrying on.")
                await asyncio.sleep(tick_s)
        finally:
            await self._stop_listeners()
            for server in self.status_servers:
                server.close()


# ---- the doctor ----


def diagnose(
    target: str,
    ports: tuple[int, ...],
    interfaces: dict[str, list[str]] | None = None,
    tailscale: str | None = None,
    studio: dict[int, bool] | None = None,
    network_name: str | None = None,
    network_name_known: bool = True,
) -> list[tuple[bool, str, str]]:
    """(ok, what was checked, what to do about it) for each check; the fix is empty when all is well."""
    interfaces = interfaces if interfaces is not None else read_interfaces()
    address = sharing_address(interfaces)
    results: list[tuple[bool, str, str]] = []
    if address:
        results.append(
            (True, f"Internet Sharing is on; the robot will see this laptop as {address}.", "")
        )
    else:
        results.append(
            (
                False,
                "Internet Sharing is not on (no sharing network found).",
                "Plug in the iPhone by USB. On this laptop open System Settings > General > Sharing > Internet Sharing. Share the iPhone USB connection to Wi-Fi, open the Wi-Fi options, name the network starting with maipai (for example maipai-trip), choose WPA2 Personal and a password, then turn Internet Sharing on.",
            )
        )
    if network_name:
        good = network_name.lower().startswith("maipai")
        results.append(
            (
                good,
                f"The sharing network is called '{network_name}'.",
                ""
                if good
                else "Rename it to start with maipai (for example maipai-trip) in the Wi-Fi options of Internet Sharing: the robot only uses this relay on such a network.",
            )
        )
    elif network_name_known is False:
        results.append(
            (
                True,
                "The sharing network's name could not be read here.",
                "Make sure it starts with maipai (it is in the Wi-Fi options of Internet Sharing).",
            )
        )
    ts = tailscale if tailscale is not None else tailscale_state()
    if ts == "on":
        results.append((True, "Tailscale is on and signed in.", ""))
    elif ts == "off":
        results.append(
            (
                False,
                "Tailscale is off or signed out.",
                "Open Tailscale in the menu bar, sign in and turn it on.",
            )
        )
    else:
        results.append(
            (True, "Tailscale could not be checked from here.", "The Studio test below decides.")
        )
    studio = studio if studio is not None else {p: _sync_probe(target, p) for p in ports}
    for port in ports:
        name = "voice" if port == ports[0] else "avatar"
        ok = bool(studio.get(port))
        results.append(
            (
                ok,
                f"The Studio answers on the {name} port {port}."
                if ok
                else f"The Studio does not answer on the {name} port {port}.",
                ""
                if ok
                else "Turn Tailscale on here, and check that the Studio at home is on and shows online in the Tailscale app (on your phone). The relay keeps trying by itself.",
            )
        )
    return results


def _sync_probe(target: str, port: int) -> bool:
    try:
        socket.create_connection((target, port), timeout=6).close()
        return True
    except OSError:
        return False


def doctor(target: str, ports: tuple[int, ...]) -> int:
    interfaces = read_interfaces()
    print("This laptop's addresses:")
    for name, addrs in sorted(interfaces.items()):
        if addrs and not name.startswith(("lo", "utun", "awdl", "llw", "gif", "stf")):
            print(f"  {name}: {', '.join(addrs)}")
    name = sharing_network_name()
    results = diagnose(
        target, ports, interfaces=interfaces, network_name=name, network_name_known=name is not None
    )
    print()
    failed = 0
    for ok, what, fix in results:
        print(("OK    " if ok else "FIX   ") + what)
        if fix:
            print("      " + fix)
        if not ok:
            failed += 1
    print("\n" + SSID_REMINDER)
    print("\nWhen all lines say OK, run: python3 trip_relay.py")
    return 1 if failed else 0


# ---- entry ----


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--bind", default=None)
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--ports", default=",".join(str(p) for p in DEFAULT_PORTS))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--status-port", type=int, default=STATUS_PORT)
    parser.add_argument("--no-status", action="store_true")
    parser.add_argument("--status-on-sharing", action="store_true")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--log", default=None)
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args(argv)
    ports = tuple(int(p) for p in args.ports.split(",") if p.strip())
    if args.check:
        return 0 if check(args.target, ports) else 1
    if args.doctor:
        return doctor(args.target, ports)
    log_path = None if args.no_log else (Path(args.log) if args.log else LOG_PATH)
    say = FileLog(log_path)
    if args.no_wait:
        bind = args.bind or sharing_address(read_interfaces())
        if bind is None:
            print(
                "Internet Sharing is not on, so there is no laptop network for the robot yet. Turn it on and run this again."
            )
            print("(To test at home without it, run with --bind 0.0.0.0.)")
            print(SSID_REMINDER)
            return 1
        try:
            asyncio.run(serve(bind, ports, args.target, say=say))
        except OSError as error:
            print(
                f"cannot listen on {bind}:{ports} ({error}). Another copy may be running; stop it and try again."
            )
            return 1
        except KeyboardInterrupt:
            pass
        return 0
    supervisor = Supervisor(
        target=args.target,
        ports=ports,
        say=say,
        notifier=Notifier(enabled=not args.no_notify),
        status_port=None if args.no_status else args.status_port,
        status_on_sharing=args.status_on_sharing,
        bind_override=args.bind,
    )
    say(f"MaiPai trip relay {VERSION} started. Log: {log_path or 'none'}. Press Ctrl-C to stop.")
    try:
        asyncio.run(supervisor.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
