"""Fixes found on the live hub (2026-10-20): clock, night camera, ring write."""

from __future__ import annotations


def test_a_hosted_body_never_gets_a_clock_setter():
    from maipai_body.app import _clock_setter

    assert _clock_setter(True) is None
    assert callable(_clock_setter(False))


def test_the_device_client_writes_all_twelve_pixels_in_one_tool_call():
    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient

    calls: list[tuple[str, dict]] = []

    class _Server:
        def call_device_tool(self, name, arguments, timeout):
            calls.append((name, arguments))
            return True

    client = XiaozhiDeviceClient.__new__(XiaozhiDeviceClient)
    client.server = _Server()
    client.timeout = 1.0
    client.set_led_colors([(index, 2 * index, 3) for index in range(12)])
    name, arguments = calls[0]
    assert name == "self.robot.set_led_colors"
    assert len(arguments) == 36
    assert arguments["led_11_red"] == 11 and arguments["led_11_green"] == 22
    try:
        client.set_led_colors([(0, 0, 0)] * 11)
    except ValueError as exc:
        assert "12" in str(exc)
    else:
        raise AssertionError("eleven colours must be refused")


def test_the_night_camera_reads_the_stream_frame_through_the_adapter_driver():
    import inspect

    from maipai_body import app

    source = inspect.getsource(app._start_stackchan_night)
    assert '_driver("camera").stream_frame' in source
    assert "robot.robot.camera.stream_frame" not in source


def test_a_connection_that_sends_no_bytes_logs_nothing_but_a_bad_request_still_does(caplog):
    import asyncio
    import logging

    from websockets.asyncio.server import serve

    from maipai_body.bodies.stackchan.ws_logging import listener_logger

    async def handler(connection):
        await connection.recv()

    async def run() -> None:
        async with serve(
            handler, "127.0.0.1", 0, logger=listener_logger("test.ws.quiet")
        ) as server:
            port = server.sockets[0].getsockname()[1]
            # The health check: connect, send nothing, close.
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.2)
            quiet = [r for r in caplog.records if r.levelno >= logging.ERROR]
            assert quiet == []
            # A garbage request is a real handshake failure and still logs.
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"NOT HTTP AT ALL\r\n\r\n")
            await writer.drain()
            await asyncio.sleep(0.3)
            writer.close()

    with caplog.at_level(logging.DEBUG, logger="test.ws.quiet"):
        asyncio.run(run())
    assert any(r.getMessage() == "opening handshake failed" for r in caplog.records)


def test_the_bundle_builds_its_face_detector_without_the_reachy_sdk():
    import inspect

    from maipai_body import app

    source = inspect.getsource(app._serve_stackchan_channels)
    assert "LazyFaceDetector(" in source
    assert "FiveLandmarkDetector" not in source and "reachy_mini" not in source


def test_a_hosted_bot_logs_the_voice_session_at_info_and_setup_is_idempotent():
    import logging

    from maipai_body.logging_setup import configure_logging

    root = logging.Logger("test-root")
    original = logging.getLogger("maipai_body").level
    try:
        configure_logging(True, root=root)
        configure_logging(True, root=root)
        assert len(root.handlers) == 1
        assert logging.getLogger("maipai_body").level == logging.INFO
        assert logging.getLogger("maipai_body.bodies.stackchan.turn").isEnabledFor(logging.INFO)
    finally:
        logging.getLogger("maipai_body").setLevel(original)


def test_the_light_poller_is_given_the_offline_rungs_that_own_the_link_machine():
    import inspect

    from maipai_body import app

    source = inspect.getsource(app._serve_stackchan_channels)
    call = source.split("start_stackchan_light(")[1].split(")")[0]
    assert "offline" in call and "link" not in call.replace("light", "")


def test_the_presence_loop_skips_the_idle_settle_while_still():
    import inspect

    from maipai_body import app

    source = inspect.getsource(app.StackChanBehavior._presence_loop)
    assert "not self.idle_still()" in source.split("self._vision")[0]


def test_a_failed_device_tool_call_logs_the_real_cause_once_a_minute(caplog):
    import logging

    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient

    class _Server:
        def call_device_tool(self, name, arguments, timeout):
            raise RuntimeError("tool rejected: led_3_red out of range")

    client = XiaozhiDeviceClient(_Server())
    with caplog.at_level(logging.WARNING, logger="maipai_body.bodies.stackchan.xiaozhi.server"):
        for _ in range(3):
            try:
                client.set_led_color(1, 2, 3)
            except Exception:
                pass
    lines = [
        r.getMessage() for r in caplog.records if "tool self.robot.set_led_color" in r.getMessage()
    ]
    assert len(lines) == 1
    assert "RuntimeError" in lines[0] and "out of range" in lines[0]


def test_local_watching_shows_no_cue_and_stops_when_the_household_says_off():
    from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
    from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient

    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    camera = robot._driver("camera")
    leds_before = [c.name for c in device.calls if "led" in c.name]

    assert robot.camera.stream(enabled=True, silent=True) is True
    assert robot.camera.stream(enabled=False) is not None
    assert [c.name for c in device.calls if "led" in c.name] == leds_before  # no ring writes

    camera.watch_allowed = lambda: False
    assert robot.camera.stream(enabled=True, silent=True) is False
    assert camera.stream_frame(0.4) is None  # nothing is read while the watch level is off


def test_a_visible_camera_stream_still_lights_and_clears_the_cue():
    from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
    from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient

    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    robot.camera.stream(enabled=True)
    assert robot._driver("leds").camera_indicator_active is True
    robot.camera.stream(enabled=False)
    assert robot._driver("leds").camera_indicator_active is False


def test_a_turn_drives_the_ring_funnel_and_the_face_together():
    from maipai_body.app import _turn_sink
    from maipai_body.presence.funnel import FunnelState

    funnel: list[FunnelState] = []
    faces: list[str] = []

    class _Light:
        def update(self, **changes):
            funnel.append(changes["funnel"])

    class _Behavior:
        def render_turn_state(self, state, *, mood=None):
            faces.append(state)

    sink = _turn_sink(_Behavior(), _Light())
    for state in ("listening", "thinking", "reply_mood", "speaking", "settle"):
        sink(state, mood="happy" if state == "reply_mood" else None)
    assert funnel == [
        FunnelState.LISTENING,
        FunnelState.THINKING,
        FunnelState.SPEAKING,
        FunnelState.IDLE,
    ]
    assert faces == ["listening", "thinking", "reply_mood", "speaking", "settle"]


def test_the_listening_cue_perks_the_head_up_with_a_happy_face():
    from maipai_body.bodies.stackchan.expression_map import PRIMITIVE_BODY_MAP

    perk = PRIMITIVE_BODY_MAP["perk"]
    assert perk.face == "happy" and perk.pitch_fraction > 0  # up from level, and brighter
    import inspect

    from maipai_body import app

    source = inspect.getsource(app.StackChanBehavior.render_turn_state)
    assert '"listening": "perk"' in source


def test_the_face_watchdog_restores_the_idle_face_after_a_lost_frame():
    from maipai_body.app import FACE_QUIET_S, StackChanBehavior
    from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
    from maipai_body.bodies.stackchan.avatar.server import control_avatar
    from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient

    device = FakeStackChanDeviceClient()
    behavior = StackChanBehavior(StackChanRobotAdapter(device).robot)
    try:
        head = behavior.robot._driver("head").expression_device
        head.send_avatar_frame(control_avatar("happy"))  # the last face shown was not idle
        assert head.last_expression == "happy"
        start = 1000.0
        assert behavior.face_watchdog(start) is False  # quiet period begins
        assert behavior.face_watchdog(start + FACE_QUIET_S - 1) is False
        assert behavior.face_watchdog(start + FACE_QUIET_S + 1) is True  # idle face resent
        assert head.last_expression == "neutral"
        assert behavior.face_watchdog(start + FACE_QUIET_S + 2) is False  # nothing stale now
        # A frame that never arrived is repaired too.
        device.connected = False
        try:
            head.send_avatar_frame(control_avatar("sad"))
        except Exception:
            pass
        device.connected = True
        assert head.last_expression_ok is False
        assert behavior.face_watchdog(start + 50.0) is True
        assert head.last_expression_ok is True
        # A turn in progress is never interrupted.
        behavior._active.set()
        head.send_avatar_frame(control_avatar("happy"))
        assert behavior.face_watchdog(start + 100.0) is False
    finally:
        behavior.close()


def test_thinking_violet_is_clearly_apart_from_the_camera_pink():
    from maipai_body.bodies.stackchan.ring import RING_RGB
    from maipai_body.hal.seam import Palette

    violet, pink = RING_RGB[Palette.MAGENTA], RING_RGB[Palette.PINK]
    assert violet[2] > violet[0] * 2  # more blue than red: violet
    assert pink[0] > pink[2]  # pink leans red
