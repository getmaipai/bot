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


def test_a_missing_face_detector_package_is_one_quiet_line_without_a_traceback():
    import inspect

    from maipai_body import app

    source = inspect.getsource(app._serve_stackchan_channels)
    assert "except ImportError:" in source
    assert "face tracking is unavailable in the hub bundle" in source
    quiet = source.split("except ImportError:")[1].split("except Exception:")[0]
    assert "exc_info" not in quiet
