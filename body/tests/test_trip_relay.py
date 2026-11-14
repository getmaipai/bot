"""The laptop trip relay (body/scripts/trip_relay.py).

Sharing address detection, byte-for-byte forwarding with a fake robot and a fake upstream, counts
only in the status lines (never the stream), an unreachable Studio reported plainly.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "trip_relay.py"
spec = importlib.util.spec_from_file_location("trip_relay", SCRIPT)
trip_relay = importlib.util.module_from_spec(spec)
sys.modules["trip_relay"] = trip_relay
spec.loader.exec_module(trip_relay)

IFCONFIG = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 172.19.211.130 netmask 0xfffff000 broadcast 172.19.223.255
bridge100: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 192.168.3.1 netmask 0xffffff00 broadcast 192.168.3.255
\tinet6 fe80::1 prefixlen 64
utun4: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1280
\tinet 100.81.94.122 --> 100.81.94.122 netmask 0xffffffff
"""


def test_parse_ifconfig_and_sharing_address():
    interfaces = trip_relay.parse_ifconfig(IFCONFIG)
    assert interfaces["en0"] == ["172.19.211.130"]
    assert interfaces["bridge100"] == ["192.168.3.1"]
    assert trip_relay.sharing_address(interfaces) == "192.168.3.1"  # whatever subnet macOS picked
    assert trip_relay.sharing_address({"en0": ["10.0.0.5"]}) is None


async def _echo_upstream(port_holder):
    async def handle(reader, writer):
        data = await reader.read(65536)
        writer.write(b"hub:" + data)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port_holder.append(server.sockets[0].getsockname()[1])
    return server


def test_forwards_bytes_and_logs_only_counts():
    async def run():
        lines: list[str] = []
        holder: list[int] = []
        upstream = await _echo_upstream(holder)
        port = holder[0]
        counters = trip_relay.Counters()
        stop = asyncio.Event()
        task = asyncio.create_task(
            trip_relay.serve(
                "127.0.0.1",
                (0,),
                "127.0.0.1",
                say=lines.append,
                stop=stop,
                counters=counters,
                status_every_s=0.0,
            )
        )
        await asyncio.sleep(0.3)
        # the first relay used port 0 (any); the checks below use a fixed pair instead
        stop.set()
        await task
        # second run: the relay listens on a free port, the target port is the upstream's
        lines.clear()
        counters = trip_relay.Counters()
        stop = asyncio.Event()
        free = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        relay_port = free.sockets[0].getsockname()[1]
        free.close()
        await free.wait_closed()
        handler = trip_relay.make_handler("127.0.0.1", port, counters, lines.append)
        relay = await asyncio.start_server(handler, "127.0.0.1", relay_port)
        reader, writer = await asyncio.open_connection("127.0.0.1", relay_port)
        secret = b"Bearer SECRET-PAIRING-TOKEN"
        writer.write(secret)
        await writer.drain()
        answer = await asyncio.wait_for(reader.read(65536), 5)
        writer.close()
        await asyncio.sleep(0.2)
        relay.close()
        upstream.close()
        return answer, lines, counters

    answer, lines, counters = asyncio.run(run())
    assert answer == b"hub:Bearer SECRET-PAIRING-TOKEN"
    assert counters.to_hub == len(b"Bearer SECRET-PAIRING-TOKEN")
    assert counters.from_hub == len(answer)
    joined = " ".join(lines)
    assert "SECRET" not in joined and "Bearer" not in joined  # the stream is never printed
    assert "robot connected" in joined


def test_unreachable_studio_is_reported_plainly_and_the_robot_is_dropped():
    async def run():
        lines: list[str] = []
        counters = trip_relay.Counters()
        free = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        dead_port = free.sockets[0].getsockname()[1]
        free.close()
        await free.wait_closed()
        handler = trip_relay.make_handler("127.0.0.1", dead_port, counters, lines.append)
        relay = await asyncio.start_server(handler, "127.0.0.1", 0)
        relay_port = relay.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", relay_port)
        data = await asyncio.wait_for(reader.read(10), 5)
        writer.close()
        relay.close()
        return data, lines, counters

    data, lines, counters = asyncio.run(run())
    assert data == b""  # closed
    assert counters.failed == 1
    assert any("Tailscale" in line for line in lines)


def test_main_refuses_to_start_without_sharing_and_says_what_to_do(monkeypatch, capsys):
    monkeypatch.setattr(trip_relay, "read_interfaces", lambda: {"en0": ["10.0.0.5"]})
    assert trip_relay.main([]) == 1
    out = capsys.readouterr().out
    assert "Internet Sharing" in out and "maipai" in out
