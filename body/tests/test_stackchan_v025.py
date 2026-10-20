"""Batch from the independent voice-path review (2026-10-20): A to E."""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

from maipai_body.bodies.stackchan.avatar.server import control_avatar
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore


def test_credentials_reader_order_matches_channel():
    from maipai_body.app import _command_credentials
    from maipai_body.link.channel import CommandChannel

    link = SimpleNamespace(
        pairing_store=SimpleNamespace(load=lambda: SimpleNamespace(base_url="http://192.0.2.10")),
        hub_client=SimpleNamespace(session_cookie="cookie-value", active_base_url=None),
    )
    base_url, cookie = _command_credentials(link)()
    assert (base_url, cookie) == ("http://192.0.2.10", "cookie-value")
    channel = CommandChannel("", "", credentials=_command_credentials(link))
    assert channel._url(base_url) == "ws://192.0.2.10/api/devices/me/events"


def test_an_expression_frame_remembers_its_name():
    frame = control_avatar("happy")
    assert isinstance(frame, bytes) and frame.expression == "happy"
    assert frame[0] == 3  # still a plain ControlAvatar frame on the wire


def test_with_no_avatar_channel_the_face_is_set_over_the_voice_socket():
    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer

    async def scenario() -> list[str]:
        server = XiaozhiServer(PairingStore(), robot=None)
        sent: list[str] = []

        async def fake_send_emotion(expression: str) -> str:
            sent.append(expression)
            return expression

        server.send_emotion = fake_send_emotion  # type: ignore[method-assign]
        server._sessions["device"] = object()

        async def refusing_sender(device_id, frame):
            raise ConnectionError("StackChan avatar channel is not connected.")

        server._avatar_frame_sender = refusing_sender
        await server.send_expression_frame(control_avatar("doubt"))
        await server.send_expression_frame(control_avatar("happy"))
        return sent

    assert asyncio.run(scenario()) == ["doubt", "happy"]


def test_a_frame_without_a_name_still_raises_when_the_avatar_channel_is_down():
    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer

    async def scenario() -> None:
        server = XiaozhiServer(PairingStore(), robot=None)
        server._sessions["device"] = object()

        async def refusing_sender(device_id, frame):
            raise ConnectionError("not connected")

        server._avatar_frame_sender = refusing_sender
        await server.send_expression_frame(b"\x03\x00\x00\x00\x00")

    try:
        asyncio.run(scenario())
    except ConnectionError:
        return
    raise AssertionError("an unnamed frame has no voice-socket equivalent")


def test_listen_mode_and_aec_reach_the_handler_when_it_accepts_them():
    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer

    async def scenario() -> list[tuple]:
        server = XiaozhiServer(PairingStore(), robot=None)
        calls: list[tuple] = []

        async def rich(session_id, device_id, state, *, mode="auto", aec=None):
            calls.append((state, mode, aec))

        async def plain(session_id, device_id, state):
            calls.append((state, "plain", None))

        server.turn_handler = rich
        await server._call_turn_handler("s", "d", "start", "realtime", True)
        await server._call_turn_handler("s", "d", "start", 7, "yes")
        server.turn_handler = plain
        await server._call_turn_handler("s", "d", "stop", "manual", False)
        return calls

    assert asyncio.run(scenario()) == [
        ("start", "realtime", True),
        ("start", "auto", None),
        ("stop", "plain", None),
    ]


def test_the_estop_recovery_asks_the_unit_instead_of_trusting_an_open_socket():
    from maipai_body import app

    source = inspect.getsource(app._serve_stackchan_channels)
    assert "device_answers" in source and "get_head_angles()" in source
    assert "EstopRecovery(voice.robot.robot, device_answers)" in source
