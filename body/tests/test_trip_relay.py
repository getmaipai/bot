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
\tinet 198.51.100.20 netmask 0xfffff000 broadcast 198.51.100.255
bridge100: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 192.168.3.1 netmask 0xffffff00 broadcast 192.168.3.255
\tinet6 fe80::1 prefixlen 64
utun4: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1280
\tinet 100.81.94.122 --> 100.81.94.122 netmask 0xffffffff
"""


def test_parse_ifconfig_and_sharing_address():
    interfaces = trip_relay.parse_ifconfig(IFCONFIG)
    assert interfaces["en0"] == ["198.51.100.20"]
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


def test_main_no_wait_refuses_to_start_without_sharing_and_says_what_to_do(monkeypatch, capsys):
    monkeypatch.setattr(trip_relay, "read_interfaces", lambda: {"en0": ["10.0.0.5"]})
    assert trip_relay.main(["--no-wait", "--no-log"]) == 1
    out = capsys.readouterr().out
    assert "Internet Sharing" in out and "maipai" in out


# ---- relay v2: notifications, log, status, supervisor, doctor ----


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_notifier_is_rate_limited_per_kind_and_can_be_switched_off():
    sent: list[str] = []
    clock = _Clock()
    notifier = trip_relay.Notifier(run=sent.append, clock=clock, gap_s=60.0)
    assert notifier.notify("robot_up", "one") is True
    assert notifier.notify("robot_up", "again") is False  # inside the minute
    assert notifier.notify("studio", "other kind") is True
    clock.now += 61
    assert notifier.notify("robot_up", "later") is True
    assert sent == ["one", "other kind", "later"]
    off = trip_relay.Notifier(enabled=False, run=sent.append)
    assert off.notify("x", "never") is False


def test_file_log_appends_with_a_time_and_restarts_past_the_cap(tmp_path):
    path = tmp_path / "logs" / "relay.log"
    out: list[str] = []
    log = trip_relay.FileLog(path, out=out.append, max_bytes=200)
    log("robot connected from 192.0.2.7 to port 62923 (open now: 1)")
    assert out == ["robot connected from 192.0.2.7 to port 62923 (open now: 1)"]
    assert "robot connected" in path.read_text()
    for _ in range(10):
        log("x" * 50)
    assert path.stat().st_size < 400  # it restarted instead of growing without end


def _status(**over):
    base = dict(
        sharing="192.168.2.1",
        tailscale="on",
        studio={62923: True, 62924: True},
        ports=(62923, 62924),
        counters=trip_relay.Counters(),
        now_wall=2000.0,
        listening=True,
    )
    base.update(over)
    return trip_relay.build_status(**base)


def test_status_says_the_next_step_in_plain_words_for_each_failure():
    assert "Internet Sharing" in _status(sharing=None)["next_step"]
    assert "Tailscale" in _status(tailscale="off")["headline"]
    down = _status(studio={62923: False, 62924: True})
    assert "Studio" in down["headline"] and "avatar ok" in " ".join(
        light["detail"] for light in down["lights"]
    )
    waiting = _status()
    assert waiting["headline"] == "Waiting for the robot" and waiting["ok"] is False
    counters = trip_relay.Counters()
    counters.by_port_active = {62923: 1, 62924: 1}
    counters.active = 2
    counters.last_robot_at = 1990.0
    good = _status(counters=counters)
    assert good["ok"] is True and "All good" in good["headline"]
    assert good["robot_last_seen"] == "10 seconds ago"


def test_status_says_when_the_relay_cannot_bind():
    status = _status(listening=False, bind_failed=True)
    assert status["headline"] == "The relay cannot start" and "Another copy" in status["next_step"]
    assert _status(listening=False)["headline"] == "Getting ready"


def test_html_escapes_and_shows_every_light():
    html = trip_relay.render_html(_status())
    assert html.count('class="dot"') == 4 and "refresh" in html
    odd = _status()
    odd["headline"] = "<script>alert(1)</script>"
    assert "<script>" not in trip_relay.render_html(odd)


def _http_get(port: int, path: str, host: str) -> bytes:
    async def go():
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"GET {path} HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(65536), 5)
        writer.close()
        return data

    return go()


def test_status_page_serves_json_and_refuses_a_foreign_host_header():
    async def run():
        server = await trip_relay.serve_status(
            lambda: _status(), "127.0.0.1", 0, {"127.0.0.1", "localhost"}
        )
        port = server.sockets[0].getsockname()[1]
        ok_json = await _http_get(port, "/status.json", f"127.0.0.1:{port}")
        html = await _http_get(port, "/", f"localhost:{port}")
        foreign = await _http_get(port, "/", "evil.example.com")
        missing = await _http_get(port, "/nope", f"127.0.0.1:{port}")
        server.close()
        return ok_json, html, foreign, missing

    ok_json, html, foreign, missing = asyncio.run(run())
    assert b"200 OK" in ok_json and b'"headline"' in ok_json
    assert b"200 OK" in html and b"MaiPai trip relay" in html
    assert b"400 Bad Request" in foreign
    assert b"404" in missing


def _supervisor(clock, interfaces, notifier, probe=None, **extra):
    async def fine(target, ports, timeout=4.0):
        return dict.fromkeys(ports, True)

    return trip_relay.Supervisor(
        target="127.0.0.1",
        ports=(62923, 62924),
        listen_ports=(0, 0),
        say=lambda line: None,
        notifier=notifier,
        interfaces=interfaces,
        probe=probe or fine,
        tailscale=lambda: "on",
        clock=clock,
        wall=clock,
        status_port=None,
        **extra,
    )


def test_supervisor_waits_for_sharing_binds_when_it_appears_and_heals_when_it_goes_and_returns():
    async def run():
        clock = _Clock()
        sent: list[str] = []
        state = {"addr": None}
        notifier = trip_relay.Notifier(run=sent.append, clock=clock, gap_s=0.0)
        sup = _supervisor(
            clock,
            lambda: {"bridge100": [state["addr"]]} if state["addr"] else {"en0": ["10.0.0.5"]},
            notifier,
        )
        await sup.tick()
        waiting = (sup.sharing, len(sup.servers))
        state["addr"] = "127.0.0.1"
        clock.now += 2
        await sup.tick()
        bound = (sup.sharing, len(sup.servers), sup.bound_to)
        state["addr"] = None
        clock.now += 2
        await sup.tick()
        gone = (len(sup.servers), list(sent))
        state["addr"] = "localhost"  # a different address: the listeners move to it
        clock.now += 2
        await sup.tick()
        back = (len(sup.servers), sup.bound_to)
        await sup._stop_listeners()
        return waiting, bound, gone, back

    waiting, bound, gone, back = asyncio.run(run())
    assert waiting == (None, 0)
    assert bound == ("127.0.0.1", 2, "127.0.0.1")
    assert gone[0] == 0 and any("Internet Sharing" in line for line in gone[1])
    assert back == (2, "localhost")


def test_supervisor_notifies_when_the_robot_connects_and_when_it_is_lost():
    async def run():
        clock = _Clock()
        sent: list[str] = []
        holder: list[int] = []
        upstream = await _hold_upstream(holder)
        notifier = trip_relay.Notifier(run=sent.append, clock=clock, gap_s=0.0)
        sup = trip_relay.Supervisor(
            target="127.0.0.1",
            ports=(holder[0], holder[0]),
            listen_ports=(0, 0),
            say=lambda line: None,
            notifier=notifier,
            interfaces=lambda: {"bridge100": ["127.0.0.1"]},
            probe=lambda target, ports, timeout=4.0: _true(ports),
            tailscale=lambda: "on",
            clock=clock,
            wall=clock,
            status_port=None,
        )
        await sup.tick()
        port = sup.bound_ports[0]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"hello")
        await writer.drain()
        await asyncio.wait_for(reader.read(100), 5)
        await asyncio.sleep(0.2)
        clock.now += 2
        await sup.tick()
        connected = list(sent)
        writer.close()
        await asyncio.sleep(0.3)
        clock.now += 2
        await sup.tick()  # the robot just closed: not "lost" yet (it may reconnect)
        before = list(sent)
        clock.now += 30
        await sup.tick()
        await sup.tick()
        after = list(sent)
        await sup._stop_listeners()
        upstream.close()
        return connected, before, after

    connected, before, after = asyncio.run(run())
    assert any("connected" in line for line in connected)
    assert not any("lost" in line for line in before)
    assert any("lost" in line for line in after)


async def _true(ports):
    return dict.fromkeys(ports, True)


async def _hold_upstream(port_holder):
    """A fake Studio that stays connected until the client closes, like the real one."""

    async def handle(reader, writer):
        try:
            while await reader.read(65536):
                writer.write(b"hub")
                await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port_holder.append(server.sockets[0].getsockname()[1])
    return server


def test_supervisor_says_when_the_studio_is_unreachable_and_survives_a_long_sleep():
    async def run():
        clock = _Clock()
        sent: list[str] = []
        notifier = trip_relay.Notifier(run=sent.append, clock=clock, gap_s=0.0)

        async def down(target, ports, timeout=4.0):
            return dict.fromkeys(ports, False)

        sup = _supervisor(clock, lambda: {"bridge100": ["127.0.0.1"]}, notifier, probe=down)
        await sup.tick()
        first = (list(sent), len(sup.servers))
        clock.now += 2
        await sup.tick(slept_s=400.0)  # the laptop slept
        return first, len(sup.servers), sup.status()["headline"], sup

    first, after_sleep, headline, sup = asyncio.run(run())
    assert any("Studio" in line for line in first[0]) and first[1] == 2
    assert after_sleep == 2  # restarted its listeners after the wake
    assert "Studio" in headline
    asyncio.run(sup._stop_listeners())


def test_diagnose_gives_a_plain_fix_for_every_failure():
    bad = trip_relay.diagnose(
        "127.0.0.1",
        (1, 2),
        interfaces={"en0": ["10.0.0.5"]},
        tailscale="off",
        studio={1: False, 2: False},
        network_name="HomeNet",
    )
    fixes = [fix for ok, _, fix in bad if not ok]
    assert len(fixes) == 5
    assert any("Internet Sharing" in fix for fix in fixes)
    assert any("maipai" in fix for fix in fixes)
    assert any("Tailscale" in fix for fix in fixes)
    good = trip_relay.diagnose(
        "127.0.0.1",
        (1, 2),
        interfaces={"bridge100": ["192.168.2.1"]},
        tailscale="on",
        studio={1: True, 2: True},
        network_name="maipai-trip",
    )
    assert all(ok for ok, _, _ in good)


def test_tailscale_state_reads_the_backend_state_and_says_unknown_without_the_tool(monkeypatch):
    class Done:
        def __init__(self, text):
            self.stdout = text

    monkeypatch.setattr(trip_relay.os.path, "exists", lambda path: True)
    assert trip_relay.tailscale_state(lambda *a, **k: Done('{"BackendState": "Running"}')) == "on"
    assert (
        trip_relay.tailscale_state(lambda *a, **k: Done('{"BackendState": "NeedsLogin"}')) == "off"
    )
    assert trip_relay.tailscale_state(lambda *a, **k: Done("not json")) == "off"
    monkeypatch.setattr(trip_relay.os.path, "exists", lambda path: False)
    assert trip_relay.tailscale_state(lambda *a, **k: Done("{}")) == "unknown"


def test_sharing_network_name_is_read_from_the_nat_settings():
    class Done:
        stdout = '{ NAT = { NetworkName = "maipai-trip"; }; }'

    assert trip_relay.sharing_network_name(lambda *a, **k: Done()) == "maipai-trip"
