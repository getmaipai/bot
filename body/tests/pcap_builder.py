"""Hand-built packet captures for the egress tests.

Every frame is synthesized here, byte by byte, from documentation-range
addresses (RFC 5737, 2001:db8::/32). None of it is a recording of a real
robot: the real capture is RM-07's, on the unit.
"""

from __future__ import annotations

import ipaddress
import socket
import struct

ROBOT = "192.0.2.10"
HUB = "192.0.2.20"
RESOLVER = "192.0.2.1"
PYPI_IP = "198.51.100.7"
STRAY_IP = "203.0.113.9"


def ethernet(payload: bytes, ethertype: int = 0x0800) -> bytes:
    return b"\x00" * 6 + b"\x00" * 6 + struct.pack("!H", ethertype) + payload


def _ip(src: str, dst: str, proto: int, body: bytes) -> bytes:
    if ":" in src:
        header = struct.pack("!IHBB", 6 << 28, len(body), proto, 64)
        header += ipaddress.IPv6Address(src).packed + ipaddress.IPv6Address(dst).packed
        return header
    header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        20 + len(body),
        0,
        0,
        64,
        proto,
        0,
        socket.inet_aton(src),
        socket.inet_aton(dst),
    )
    return header


def tcp_frame(src, sport, dst, dport, *, flags=0x02, payload=b"") -> bytes:
    tcp = struct.pack("!HHIIBBHHH", sport, dport, 0, 0, 5 << 4, flags, 65535, 0, 0) + payload
    ip = _ip(src, dst, 6, tcp)
    return ethernet(ip + tcp, 0x86DD if ":" in src else 0x0800)


def ipv4_fragment(
    src: str,
    dst: str,
    *,
    offset: int = 1,
    more_fragments: bool = False,
    payload=b"hidden outbound data",
) -> bytes:
    """An IPv4 fragment: addresses remain visible, transport ports may not."""
    header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        20 + len(payload),
        0x4242,
        offset | (0x2000 if more_fragments else 0),
        64,
        6,
        0,
        socket.inet_aton(src),
        socket.inet_aton(dst),
    )
    return ethernet(header + payload)


def udp_frame(src, sport, dst, dport, payload=b"") -> bytes:
    udp = struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload
    ip = _ip(src, dst, 17, udp)
    return ethernet(ip + udp, 0x86DD if ":" in src else 0x0800)


def icmp_frame(src, dst) -> bytes:
    body = struct.pack("!BBHI", 8, 0, 0, 0)
    return ethernet(_ip(src, dst, 1, body) + body)


def dns_query_name(name: str) -> bytes:
    return b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"


def dns_response(name: str, address: str, *, compress: bool = True) -> bytes:
    header = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 1, 0, 0)
    qname = dns_query_name(name)
    qtype = 28 if ":" in address else 1
    question = qname + struct.pack("!HH", qtype, 1)
    owner = b"\xc0\x0c" if compress else qname
    rdata = ipaddress.ip_address(address).packed
    answer = owner + struct.pack("!HHIH", qtype, 1, 60, len(rdata)) + rdata
    return header + question + answer


def client_hello(sni: str) -> bytes:
    name = sni.encode()
    server_name = struct.pack("!BH", 0, len(name)) + name
    sni_list = struct.pack("!H", len(server_name)) + server_name
    extension = struct.pack("!HH", 0, len(sni_list)) + sni_list
    body = b"\x03\x03" + b"\x00" * 32 + b"\x00" + struct.pack("!H", 2) + b"\x13\x01"
    body += b"\x01\x00" + struct.pack("!H", len(extension)) + extension
    handshake = b"\x01" + len(body).to_bytes(3, "big") + body
    return b"\x16\x03\x01" + struct.pack("!H", len(handshake)) + handshake


def pcap(frames: list[bytes], *, linktype: int = 1, start: float = 1000.0) -> bytes:
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, linktype)
    for i, frame in enumerate(frames):
        ts = start + i * 0.01
        out += struct.pack("<IIII", int(ts), int((ts % 1) * 1_000_000), len(frame), len(frame))
        out += frame
    return out


def pcapng(frames: list[bytes], *, linktype: int = 1) -> bytes:
    def block(kind: int, body: bytes) -> bytes:
        body += b"\x00" * (-len(body) % 4)
        total = 12 + len(body)
        return struct.pack("<II", kind, total) + body + struct.pack("<I", total)

    out = block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
    out += block(1, struct.pack("<HHI", linktype, 0, 65535))
    for i, frame in enumerate(frames):
        micros = 1_000_000_000 + i * 10_000
        body = struct.pack("<IIIII", 0, micros >> 32, micros & 0xFFFFFFFF, len(frame), len(frame))
        out += block(6, body + frame)
    return out


def sample_session() -> list[bytes]:
    """A session the design allows: the hub, a PyPI check by name, DNS, mDNS, DHCP."""
    return [
        udp_frame(ROBOT, 40001, RESOLVER, 53, dns_query_name("pypi.org")),
        udp_frame(RESOLVER, 53, ROBOT, 40001, dns_response("pypi.org", PYPI_IP)),
        tcp_frame(ROBOT, 50001, HUB, 8443, flags=0x02),
        tcp_frame(HUB, 8443, ROBOT, 50001, flags=0x12),
        tcp_frame(ROBOT, 50001, HUB, 8443, flags=0x18, payload=b"x" * 300),
        tcp_frame(ROBOT, 50002, PYPI_IP, 443, flags=0x02),
        tcp_frame(ROBOT, 50002, PYPI_IP, 443, flags=0x18, payload=client_hello("pypi.org")),
        udp_frame(ROBOT, 5353, "224.0.0.251", 5353, b"\x00" * 20),
        udp_frame(ROBOT, 68, "255.255.255.255", 67, b"\x00" * 30),
    ]
