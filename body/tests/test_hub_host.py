from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

from maipai_body.hub_host import (
    _check_data_dir,
    _parser,
    _port,
    _runtime_environment,
)


def test_port_validation():
    assert _port("65535") == 65535
    for value in ("0", "65536", "nope"):
        try:
            _port(value)
        except Exception:
            continue
        raise AssertionError(f"accepted invalid port {value}")


def test_required_launcher_arguments():
    try:
        _parser().parse_args(["run"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("run accepted missing required arguments")


def test_hub_url_validation_and_duplicate_ports(tmp_path, capsys):
    from maipai_body.hub_host import main

    for url in ("", "ftp://home.local"):
        try:
            # Parser accepts the string; main reports the actionable validation error.
            import sys

            old = sys.argv
            sys.argv = [
                "maipai-bot-host",
                "run",
                "--data-dir",
                str(tmp_path),
                "--hub-url",
                url,
                "--voice-port",
                "18001",
                "--avatar-port",
                "18002",
            ]
            assert main() == 2
        finally:
            sys.argv = old
    assert "hub URL" in capsys.readouterr().err
    try:
        old = sys.argv
        sys.argv = [
            "maipai-bot-host",
            "run",
            "--data-dir",
            str(tmp_path),
            "--hub-url",
            "http://home.local",
            "--voice-port",
            "18001",
            "--avatar-port",
            "18001",
        ]
        assert main() == 2
    finally:
        sys.argv = old
    assert "different" in capsys.readouterr().err


def test_env_mapping_and_ephemeral_vision_port(tmp_path):
    args = _parser().parse_args(
        [
            "run",
            "--data-dir",
            str(tmp_path),
            "--hub-url",
            "http://home.local:8800",
            "--voice-port",
            "18765",
            "--avatar-port",
            "18766",
            "--label",
            "Office",
        ]
    )
    env = _runtime_environment(args)
    assert env["MAIPAI_BODY"] == "stackchan"
    assert env["MAIPAI_BOT_DATA_DIR"] == str(tmp_path)
    assert env["MAIPAI_XIAOZHI_HOST"] == "0.0.0.0"
    assert env["MAIPAI_XIAOZHI_PORT"] == "18765"
    assert env["MAIPAI_STACKCHAN_AVATAR_PORT"] == "18766"
    assert env["MAIPAI_HUB_URL"] == "http://home.local:8800"
    assert env["MAIPAI_VISION_PORT"] == "0"


def test_vision_port_zero_is_unique_and_readable(tmp_path):
    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer
    from maipai_body.link.store import PairingStore

    first = XiaozhiServer(PairingStore(tmp_path / "one.json"), None, vision_port=0)
    second = XiaozhiServer(PairingStore(tmp_path / "two.json"), None, vision_port=0)

    async def start(server):
        await server.start("127.0.0.1", 0)
        return server.vision_port

    import asyncio

    async def both():
        try:
            return await asyncio.gather(start(first), start(second))
        finally:
            await first.close()
            await second.close()

    ports = asyncio.run(both())
    assert ports[0] > 0 and ports[1] > 0 and ports[0] != ports[1]


def test_port_taken_raises_repairs_status(tmp_path):
    with socket.socket() as bound:
        bound.bind(("0.0.0.0", 0))
        port = bound.getsockname()[1]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "maipai_body.hub_host",
                "run",
                "--data-dir",
                str(tmp_path / "data"),
                "--hub-url",
                "http://127.0.0.1:8000",
                "--voice-port",
                str(port),
                "--avatar-port",
                "8766",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 75
        assert result.stderr.strip() == (
            f"Port {port} is in use by another program. Home will show this in Repairs."
        )


def test_data_dir_must_be_writable(tmp_path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("file", encoding="utf-8")
    try:
        _check_data_dir(blocked)
    except ValueError as exc:
        assert "not writable" in str(exc)
        assert "--data-dir" in str(exc)
    else:
        raise AssertionError("accepted a non-writable data directory")


def test_stackchan_import_without_reachy_sdk():
    code = (
        "import os,sys; os.environ['MAIPAI_BODY']='stackchan'; "
        "sys.modules['reachy_mini']=None; import maipai_body.app"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
