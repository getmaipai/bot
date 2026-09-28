"""G4's own acceptance: parsing a discovered service, without any real
mDNS traffic - the network browse itself is a thin, untested wrapper
(the same shape other network-touching code in this session leaves to
live verification), but the parsing logic is a pure function."""

from __future__ import annotations

from maipai_body.link.discovery import HubAddress, _RawService, parse_service_info


def test_parses_a_well_formed_service():
    raw = _RawService(
        addresses=["192.0.2.10"],
        port=80,
        properties={b"id": b"hub-abc123", b"name": b"The Torres House", b"tls": b"0", b"v": b"1"},
    )

    address = parse_service_info(raw)

    assert address == HubAddress(
        host="192.0.2.10", port=80, instance_id="hub-abc123", name="The Torres House", tls=False
    )


def test_parses_tls_true():
    raw = _RawService(
        addresses=["192.0.2.10"], port=443, properties={b"id": b"hub-1", b"tls": b"1"}
    )

    address = parse_service_info(raw)

    assert address is not None
    assert address.tls is True


def test_no_addresses_returns_none():
    raw = _RawService(addresses=[], port=80, properties={b"id": b"hub-1"})

    assert parse_service_info(raw) is None


def test_missing_instance_id_returns_none():
    """A hub advertising a TXT record shape this client doesn't
    recognize is skipped, not guessed at - `parse_service_info` never
    raises on a malformed record."""
    raw = _RawService(addresses=["192.0.2.10"], port=80, properties={b"name": b"no id field"})

    assert parse_service_info(raw) is None


def test_missing_name_defaults_to_empty_string():
    raw = _RawService(addresses=["192.0.2.10"], port=80, properties={b"id": b"hub-1"})

    address = parse_service_info(raw)

    assert address is not None
    assert address.name == ""


def test_prefers_the_first_address_when_several_are_present():
    raw = _RawService(addresses=["192.0.2.10", "192.0.2.11"], port=80, properties={b"id": b"hub-1"})

    address = parse_service_info(raw)

    assert address is not None
    assert address.host == "192.0.2.10"
