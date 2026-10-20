"""BOT-SELF-TEST-01: the live-service wiring of the StackChan self-test."""

from __future__ import annotations

import asyncio
import json
import threading
import urllib.request

from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.uplink_stats import UplinkStats
from maipai_body.selftest.stackchan_wiring import (
    build_context,
    build_service_hooks,
    decodes_as_jpeg,
)


class _Light:
    def __init__(self) -> None:
        self.looks: list[object] = []
        self.held = False

    def show(self, look) -> None:
        assert self.held, "looks are only shown while the light service is suspended"
        self.looks.append(look)

    def suspended(self):
        import contextlib

        @contextlib.contextmanager
        def hold():
            self.held = True
            try:
                yield self
            finally:
                self.held = False

        return hold()


def test_decodes_as_jpeg_is_a_structural_check():
    assert decodes_as_jpeg(b"\xff\xd8" + b"x" * 200 + b"\xff\xd9")
    assert not decodes_as_jpeg(b"\xff\xd8abc")
    assert not decodes_as_jpeg(b"not a jpeg" * 40)


def test_the_hooks_list_seven_checks_and_hold_the_ring_while_running():
    light = _Light()
    uplink = UplinkStats(sleep=lambda s: None)
    context = build_context(
        robot=None,
        client=FakeStackChanDeviceClient(),
        light=light,
        uplink=uplink,
        link=None,
        turn_factory=lambda base, cookie: None,
        sleep=lambda s: None,
    )
    listing, run = build_service_hooks(context, light)
    assert [item["name"] for item in listing()] == [
        "led",
        "movement",
        "hearing",
        "wakeword",
        "speech",
        "reply",
        "camera",
    ]
    results = run(["led"])
    assert [r["name"] for r in results] == ["led"]
    assert results[0]["status"] == "pass"
    assert len(light.looks) == 6  # five looks and the final dark
    assert light.held is False
    try:
        run(["nope"])
    except ValueError as exc:
        assert "led" in str(exc)
    else:
        raise AssertionError("an unknown check name must be refused")


def test_the_reply_check_reports_no_hub_session_with_a_plain_fix():
    class _Link:
        class hub_client:  # noqa: N801
            session_cookie = None
            active_base_url = None

        class pairing_store:  # noqa: N801
            @staticmethod
            def load():
                return None

    light = _Light()
    context = build_context(
        robot=None,
        client=FakeStackChanDeviceClient(),
        light=light,
        uplink=UplinkStats(sleep=lambda s: None),
        link=_Link,
        turn_factory=lambda base, cookie: None,
        sleep=lambda s: None,
    )
    _, run = build_service_hooks(context, light)
    result = run(["reply"])[0]
    assert result["status"] == "fail"
    assert "hub" in result["fix"].lower()


def test_the_service_routes_are_local_only_json_and_refuse_unknown_checks():
    from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer

    async def scenario(tmp_path) -> None:
        server = XiaozhiServer(PairingStore(tmp_path / "pair.json"), robot=None, vision_port=0)
        server.selftest_checks = lambda: [{"name": "led", "title": "LED"}]

        def runner(only):
            if only and "nope" in only:
                raise ValueError("Unknown check 'nope'. Valid checks: led")
            return [{"name": "led", "status": "pass", "detail": "ok", "fix": "", "seconds": 0.1}]

        server.selftest_runner = runner
        await server.start("127.0.0.1", 0)
        port = server.vision_port
        base = f"http://127.0.0.1:{port}"

        def call(path, body=None, headers=None):
            request = urllib.request.Request(
                base + path,
                data=None if body is None else json.dumps(body).encode(),
                headers=headers or {},
                method="GET" if body is None else "POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as error:
                return error.code, json.loads(error.read())

        try:
            status, body = await asyncio.to_thread(call, "/selftest/checks")
            assert status == 200 and body["checks"][0]["name"] == "led"
            json_header = {"Content-Type": "application/json"}
            status, body = await asyncio.to_thread(call, "/selftest/run", {}, json_header)
            assert status == 200 and body["results"][0]["status"] == "pass"
            status, body = await asyncio.to_thread(
                call, "/selftest/run", {"only": ["nope"]}, json_header
            )
            assert status == 400 and "Valid checks" in body["error"]
            status, body = await asyncio.to_thread(
                call, "/selftest/run", {}, {**json_header, "Origin": "http://evil.example"}
            )
            assert status == 403
            status, _ = await asyncio.to_thread(call, "/selftest/run", {}, {})
            assert status in {415, 400}
        finally:
            await server.close()

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        asyncio.run(scenario(Path(directory)))
    assert threading.active_count() >= 1
