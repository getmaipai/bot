"""RM-07's egress tooling: read a capture, group what the robot opened, label it
against the design's allowed list, and keep the privacy page's rows from the generator."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pcap_builder import (
    HUB,
    PYPI_IP,
    RESOLVER,
    ROBOT,
    STRAY_IP,
    client_hello,
    dns_response,
    icmp_frame,
    ipv4_fragment,
    pcap,
    pcapng,
    sample_session,
    tcp_frame,
    udp_frame,
)

from maipai_body.measure import netcapture as nc

HUB_TARGET = nc.HubTarget("192.0.2.20", 8443)
PAGE = Path(__file__).parent.parent.parent / "docs" / "user" / "reachy-mini-privacy.md"


def _rows(frames, **kwargs):
    packets = nc.read_pcap(pcap(frames))
    return nc.label_groups(nc.group_egress(packets, robot_ip=ROBOT), hub=HUB_TARGET, **kwargs)


def test_reads_classic_pcap_and_pcapng_to_the_same_packets():
    classic = nc.read_pcap(pcap(sample_session()))
    ng = nc.read_pcap(pcapng(sample_session()))
    assert [(p.proto, p.src, p.sport, p.dst, p.dport, p.length) for p in classic] == [
        (p.proto, p.src, p.sport, p.dst, p.dport, p.length) for p in ng
    ]
    assert len(classic) == len(sample_session())


def test_reads_linux_cooked_and_raw_ip_link_types():
    eth = tcp_frame(ROBOT, 5, HUB, 8443)
    raw_ip = eth[14:]
    cooked = b"\x00\x00\x00\x01\x00\x06" + b"\x00" * 8 + b"\x08\x00" + raw_ip
    assert nc.read_pcap(pcap([raw_ip], linktype=101))[0].dst == HUB
    assert nc.read_pcap(pcap([cooked], linktype=113))[0].dst == HUB


def test_a_file_that_is_not_a_capture_is_refused():
    with pytest.raises(ValueError, match="not a pcap"):
        nc.read_pcap(b"hello world, this is not a capture")


def test_a_truncated_last_packet_is_dropped_not_fatal():
    data = pcap(sample_session())
    assert len(nc.read_pcap(data[:-5])) == len(sample_session()) - 1


def test_only_connections_the_robot_opened_count_as_egress():
    frames = [
        tcp_frame(HUB, 40000, ROBOT, 8000, flags=0x02),  # the hub dialling the robot
        tcp_frame(ROBOT, 8000, HUB, 40000, flags=0x12),
        tcp_frame(ROBOT, 50001, HUB, 8443, flags=0x02),
        tcp_frame(HUB, 8443, ROBOT, 50001, flags=0x12),
    ]
    groups = nc.group_egress(nc.read_pcap(pcap(frames)), robot_ip=ROBOT)
    assert [(g.proto, g.host, g.port) for g in groups] == [("tcp", HUB, 8443)]


def test_groups_by_destination_and_port_with_flow_packet_and_byte_counts():
    frames = [
        tcp_frame(ROBOT, 50001, HUB, 8443),
        tcp_frame(ROBOT, 50001, HUB, 8443, flags=0x18, payload=b"x" * 100),
        tcp_frame(ROBOT, 50002, HUB, 8443),
        tcp_frame(ROBOT, 50003, HUB, 9000),
    ]
    groups = {(g.host, g.port): g for g in nc.group_egress(nc.read_pcap(pcap(frames)), ROBOT)}
    hub = groups[(HUB, 8443)]
    assert (hub.flows, hub.packets) == (2, 3)
    assert hub.bytes_out == sum(len(f) for f in frames[:3])
    assert groups[(HUB, 9000)].flows == 1


def test_names_come_from_dns_answers_and_tls_sni_in_the_same_capture():
    frames = [
        udp_frame(RESOLVER, 53, ROBOT, 40001, dns_response("files.pythonhosted.org", PYPI_IP)),
        tcp_frame(ROBOT, 50002, PYPI_IP, 443),
        tcp_frame(
            ROBOT, 50004, STRAY_IP, 443, flags=0x18, payload=client_hello("tracker.example.com")
        ),
    ]
    hosts = {g.host for g in nc.group_egress(nc.read_pcap(pcap(frames)), ROBOT)}
    assert hosts == {"files.pythonhosted.org", "tracker.example.com"}


def test_the_sample_session_is_labelled_against_the_allowed_list():
    rows = _rows(sample_session())
    by_rule = {r.rule: r for r in rows}
    assert set(by_rule) == {"hub", "update-check", "dns", "mdns", "dhcp"}
    assert all(r.listed for r in rows)
    assert nc.unlisted(rows) == []
    assert by_rule["hub"].port == 8443 and by_rule["hub"].flows == 1


def test_an_unlisted_endpoint_fails_the_check():
    frames = sample_session() + [tcp_frame(ROBOT, 50009, STRAY_IP, 443)]
    rows = _rows(frames)
    bad = nc.unlisted(rows)
    assert [(r.host, r.port) for r in bad] == [(STRAY_IP, 443)]
    assert not nc.passes(rows)


@pytest.mark.parametrize(
    "frame",
    [
        tcp_frame(ROBOT, 50009, HUB, 22),  # the hub's address on the wrong port
        udp_frame(ROBOT, 40009, "8.8.8.8", 53, b"q"),  # a public resolver
        tcp_frame(ROBOT, 50009, PYPI_IP, 80),  # the right name on the wrong port
        icmp_frame(ROBOT, STRAY_IP),
        udp_frame(ROBOT, 123, "203.0.113.50", 123, b"n" * 48),  # NTP to the internet
    ],
)
def test_near_misses_are_unlisted(frame):
    frames = [udp_frame(RESOLVER, 53, ROBOT, 1, dns_response("pypi.org", PYPI_IP)), frame]
    assert nc.unlisted(_rows(frames)) != []


def test_dns_to_the_local_resolver_is_listed_but_never_counts_as_leaving_the_house():
    rows = _rows([udp_frame(ROBOT, 40001, RESOLVER, 53, b"q")])
    assert rows[0].rule == "dns" and rows[0].scope == "local"


def test_the_private_address_is_masked_in_the_table_and_the_hub_is_named_as_such():
    table = nc.render_capture_table(_rows(sample_session()))
    assert "192.0.2." not in table
    assert "your hub" in table
    assert "pypi.org" in table


def test_the_stray_public_address_is_printed_so_it_can_be_chased():
    table = nc.render_capture_table(_rows(sample_session() + [tcp_frame(ROBOT, 5, STRAY_IP, 443)]))
    assert f"{STRAY_IP}" in table and "not on the list" in table


def test_the_page_block_comes_from_the_generator_and_a_capture_narrows_it():
    expected = nc.render_page_block(None)
    for rule in nc.ALLOWED:
        assert rule.what in expected
    observed = nc.render_page_block(_rows([tcp_frame(ROBOT, 50001, HUB, 8443)]), source="a capture")
    assert nc.ALLOWED_BY_ID["hub"].what in observed
    assert nc.ALLOWED_BY_ID["update-check"].what not in observed


def test_the_committed_privacy_page_matches_the_generator():
    """The page's rows come from the generator: edit `netcapture.ALLOWED`, then
    `scripts/measure_rm07_egress.py --write-page`, never the block by hand."""
    assert nc.page_diff(PAGE.read_text(), nc.render_page_block(None)) == []


def test_page_diff_names_a_hand_edit_and_replace_page_block_repairs_it():
    text = PAGE.read_text()
    edited = text.replace("Your MaiPai Home", "Somebody else's server")
    diff = nc.page_diff(edited, nc.render_page_block(None))
    assert any(line.startswith("-") and "Somebody else" in line for line in diff)
    fixed = nc.replace_page_block(edited, nc.render_page_block(None))
    assert nc.page_diff(fixed, nc.render_page_block(None)) == []
    assert fixed == text


def test_page_without_markers_is_an_error_not_a_pass():
    with pytest.raises(ValueError, match="markers"):
        nc.page_diff("# no table here\n", nc.render_page_block(None))


def test_a_hub_given_by_name_matches_its_dns_answer():
    frames = [
        udp_frame(RESOLVER, 53, ROBOT, 1, dns_response("home.example.com", HUB)),
        tcp_frame(ROBOT, 50001, HUB, 8443),
    ]
    packets = nc.read_pcap(pcap(frames))
    rows = nc.label_groups(
        nc.group_egress(packets, ROBOT), hub=nc.HubTarget("home.example.com", 8443)
    )
    assert [r.rule for r in rows] == ["hub"]


def test_hub_target_parses_host_and_port():
    assert nc.HubTarget.parse("192.0.2.20:8443") == nc.HubTarget("192.0.2.20", 8443)
    assert nc.HubTarget.parse("home.example.com") == nc.HubTarget("home.example.com", 443)
    assert nc.HubTarget.parse("[2001:db8::1]:8443") == nc.HubTarget("2001:db8::1", 8443)
    with pytest.raises(ValueError):
        nc.HubTarget.parse("")


def test_tcpdump_capture_builds_the_command_and_stops_it_cleanly(tmp_path):
    calls = []

    class FakeProc:
        def send_signal(self, sig):
            calls.append(("signal", sig))

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            return 0

    def popen(cmd, **kwargs):
        calls.append(("popen", cmd))
        return FakeProc()

    out = tmp_path / "x.pcap"
    nc.capture_tcpdump(
        "eth0", out, seconds=0.0, popen=popen, sleep=lambda s: calls.append(("sleep", s))
    )
    cmd = calls[0][1]
    assert cmd[0] == "tcpdump" and "-w" in cmd and str(out) in cmd and "-n" in cmd
    assert cmd[cmd.index("-i") + 1] == "eth0"
    assert [c[0] for c in calls] == ["popen", "sleep", "signal", "wait"]


def test_tcpdump_missing_is_a_clear_error(tmp_path):
    def popen(cmd, **kwargs):
        raise FileNotFoundError("tcpdump")

    with pytest.raises(RuntimeError, match="tcpdump"):
        nc.capture_tcpdump("eth0", tmp_path / "x.pcap", seconds=0.0, popen=popen)


def test_rehearsal_on_loopback_captures_real_packets_and_flags_the_stray(tmp_path):
    try:
        result = nc.rehearse(tmp_path / "rehearsal.pcap", stray=True)
    except nc.CaptureUnavailable as err:
        pytest.skip(str(err))
    rows = nc.label_groups(
        nc.group_egress(nc.read_pcap(result.pcap.read_bytes()), robot_ip="127.0.0.1"),
        hub=result.hub,
    )
    assert [r.rule for r in rows if r.listed] == ["hub"]
    assert [r.port for r in nc.unlisted(rows)] == [result.stray_port]


def test_rehearsal_without_the_stray_passes(tmp_path):
    try:
        result = nc.rehearse(tmp_path / "rehearsal.pcap", stray=False)
    except nc.CaptureUnavailable as err:
        pytest.skip(str(err))
    rows = nc.label_groups(
        nc.group_egress(nc.read_pcap(result.pcap.read_bytes()), robot_ip="127.0.0.1"),
        hub=result.hub,
    )
    assert nc.passes(rows) and rows


# --- the script ---------------------------------------------------------------

SCRIPT = Path(__file__).parent.parent / "scripts" / "measure_rm07_egress.py"


def _script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60
    )


def test_script_prints_the_table_for_a_sample_pcap_and_exits_zero(tmp_path):
    path = tmp_path / "sample.pcap"
    path.write_bytes(pcap(sample_session()))
    result = _script("--pcap", str(path), "--robot-ip", ROBOT, "--hub", f"{HUB}:8443")
    assert result.returncode == 0, result.stderr
    assert "| What | Where it goes |" in result.stdout
    assert "pypi.org" in result.stdout and "result: pass" in result.stdout
    assert "192.0.2." not in result.stdout


def test_script_fails_on_an_unlisted_endpoint_and_names_it(tmp_path):
    path = tmp_path / "stray.pcap"
    path.write_bytes(pcap(sample_session() + [tcp_frame(ROBOT, 50009, STRAY_IP, 443)]))
    result = _script("--pcap", str(path), "--robot-ip", ROBOT, "--hub", f"{HUB}:8443")
    assert result.returncode == 1
    assert f"NOT ON THE LIST: tcp {STRAY_IP}:443" in result.stdout


@pytest.mark.parametrize(
    "fragment",
    [
        ipv4_fragment(ROBOT, STRAY_IP, offset=1),
        ipv4_fragment(ROBOT, STRAY_IP, offset=0, more_fragments=True),
    ],
    ids=("noninitial-fragment-hides-endpoint", "initial-fragment-missing-tail"),
)
def test_script_fails_and_counts_fragments_that_hide_an_outbound_endpoint(tmp_path, fragment):
    path = tmp_path / "fragmented-stray.pcap"
    path.write_bytes(pcap([fragment]))
    result = _script("--pcap", str(path), "--robot-ip", ROBOT, "--hub", f"{HUB}:8443")
    assert result.returncode == 1
    assert "ignored IP fragments: 1; capture is incomplete" in result.stdout
    assert "result: FAIL, capture contains ignored IP fragments" in result.stdout


def test_script_check_page_passes_on_the_committed_page():
    result = _script("--check-page")
    assert result.returncode == 0, result.stdout
    assert "matches the generator" in result.stdout


def test_script_refuses_to_record_or_write_a_stand_in_or_a_sim_capture(tmp_path):
    rehearsal = _script("--rehearse", "--record")
    assert rehearsal.returncode == 2 and "stand-in" in rehearsal.stderr
    path = tmp_path / "sample.pcap"
    path.write_bytes(pcap(sample_session()))
    sim = _script(
        "--pcap", str(path), "--robot-ip", ROBOT, "--hub", HUB, "--mode", "sim", "--write-page"
    )
    assert sim.returncode == 2 and "--mode unit" in sim.stderr


def test_script_needs_the_robot_and_hub_addresses_for_a_capture(tmp_path):
    result = _script("--pcap", str(tmp_path / "x.pcap"))
    assert result.returncode == 2 and "--robot-ip and --hub" in result.stderr


def test_script_reads_a_missing_file_as_a_clear_error(tmp_path):
    result = _script("--pcap", str(tmp_path / "x.pcap"), "--robot-ip", ROBOT, "--hub", HUB)
    assert result.returncode == 2 and "cannot read" in result.stderr


def test_script_rehearsal_exit_codes_follow_the_stray(tmp_path):
    probe = _script("--rehearse")
    if probe.returncode == 2 and "not run" in probe.stderr:
        pytest.skip(probe.stderr.strip())
    assert probe.returncode == 0, probe.stdout + probe.stderr
    assert _script("--rehearse", "--stray").returncode == 1
