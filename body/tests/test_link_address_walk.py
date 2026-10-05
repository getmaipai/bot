"""LINK-STATE-01: the address walk tries the LAN before the tailnet entry."""

from __future__ import annotations

from maipai_body.link.address_walk import (
    AddressWalker,
    HubEndpoint,
    PathKind,
    classify_base_url,
    no_tailnet_endpoints,
)
from maipai_body.link.discovery import HubAddress

PAIRED = "http://192.0.2.10:80"
MDNS_HOST = "http://192.0.2.77:80"
TAILNET = HubEndpoint(PathKind.TAILNET, "http://hub.tail1234.ts.net:80", "tailnet")


def _mdns(host: str = "192.0.2.77"):
    calls: list[float] = []

    def discover(timeout_s: float):
        calls.append(timeout_s)
        return HubAddress(host=host, port=80, instance_id="hub-test", name="Hub", tls=False)

    discover.calls = calls  # type: ignore[attr-defined]
    return discover


def _walker(answers: dict[str, bool], *, paired=PAIRED, discover=None, tailnet=lambda: [TAILNET]):
    tried: list[str] = []
    attempts: list[str] = []

    def try_endpoint(endpoint: HubEndpoint):
        tried.append(endpoint.base_url)
        ok = answers.get(endpoint.base_url, False)
        return ok, None if ok else "unreachable: ConnectTimeout"

    walker = AddressWalker(
        paired_base_url=lambda: paired,
        discover=discover or _mdns(),
        tailnet=tailnet,
        try_endpoint=try_endpoint,
        on_attempt=lambda e: attempts.append(e.base_url),
    )
    return walker, tried, attempts


def test_classify_separates_lan_from_tailnet_names_and_addresses():
    assert classify_base_url("http://192.0.2.10:80") is PathKind.LAN
    assert classify_base_url("https://hub.local:443") is PathKind.LAN
    assert classify_base_url("http://hub.tail1234.ts.net:80") is PathKind.TAILNET
    assert classify_base_url("http://100.100.1.2:80") is PathKind.TAILNET
    assert classify_base_url("http://100.64.0.1:80") is PathKind.TAILNET
    assert classify_base_url("http://100.128.0.1:80") is PathKind.LAN  # outside 100.64.0.0/10


def test_the_walk_tries_lan_before_the_tailnet_entry():
    walker, tried, _ = _walker({TAILNET.base_url: True})
    result = walker.walk()
    assert tried == [PAIRED, MDNS_HOST, TAILNET.base_url]
    assert result.answered is not None
    assert result.answered.kind is PathKind.TAILNET


def test_the_first_answer_stops_the_walk_and_mdns_is_never_asked():
    discover = _mdns()
    walker, tried, _ = _walker({PAIRED: True}, discover=discover)
    result = walker.walk()
    assert tried == [PAIRED]
    assert discover.calls == []
    assert result.answered is not None and result.answered.kind is PathKind.LAN


def test_a_paired_tailnet_address_is_tried_after_the_lan_ones():
    paired = "http://hub.tail1234.ts.net:80"
    walker, tried, _ = _walker({}, paired=paired, tailnet=lambda: [])
    walker.walk()
    assert tried == [MDNS_HOST, paired]


def test_the_default_tailnet_provider_is_an_empty_seam():
    # ROBOT-TAILSCALE-01 replaces this provider; until then the walk is LAN only.
    assert no_tailnet_endpoints() == []
    walker = AddressWalker(
        paired_base_url=lambda: PAIRED,
        discover=_mdns(),
        try_endpoint=lambda e: (False, "unreachable: x"),
    )
    result = walker.walk()
    assert [a.endpoint.base_url for a in result.attempts] == [PAIRED, MDNS_HOST]
    assert result.answered is None


def test_a_discovered_address_equal_to_the_paired_one_is_not_tried_twice():
    walker, tried, _ = _walker({}, discover=_mdns("192.0.2.10"), tailnet=lambda: [])
    walker.walk()
    assert tried == [PAIRED]


def test_the_result_records_each_attempt_and_its_error():
    walker, _, attempts = _walker({})
    result = walker.walk()
    assert attempts == [PAIRED, MDNS_HOST, TAILNET.base_url]
    assert [a.ok for a in result.attempts] == [False, False, False]
    assert {a.error for a in result.attempts} == {"unreachable: ConnectTimeout"}


def test_no_paired_address_still_walks_what_it_can_find():
    walker, tried, _ = _walker({}, paired=None, tailnet=lambda: [])
    walker.walk()
    assert tried == [MDNS_HOST]


def test_a_discovery_failure_is_an_attempt_with_an_error_not_a_crash():
    def broken(timeout_s: float):
        raise OSError("multicast filtered")

    walker, tried, _ = _walker({}, discover=broken, tailnet=lambda: [])
    result = walker.walk()
    assert tried == [PAIRED]
    assert any("multicast filtered" in (a.error or "") for a in result.attempts)
