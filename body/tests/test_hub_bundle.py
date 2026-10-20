from __future__ import annotations

import os
import socket
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.bundle
@pytest.mark.skipif(
    os.environ.get("MAIPAI_BOT_BUNDLE_TEST") != "1",
    reason="set MAIPAI_BOT_BUNDLE_TEST=1 in the Mac bench lane",
)
def test_darwin_bundle_starts_voice_listener(tmp_path):
    tag = "v0.1.0"
    output_dir = tmp_path / "release"
    env = {**os.environ, "MAIPAI_BOT_BUNDLE_OUT_DIR": str(output_dir)}
    subprocess.run(
        [str(ROOT / "scripts/build-hub-bundle.sh"), tag, "darwin-arm64"],
        cwd=ROOT,
        check=True,
        timeout=900,
        env=env,
    )
    archive = output_dir / "bot-darwin-arm64.tar.gz"
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(tmp_path, filter="data")
    bot = tmp_path / "bot"
    voice, avatar = _free_port(), _free_port()
    while avatar == voice:
        avatar = _free_port()
    data_dir = tmp_path / "data"
    command = [
        str(bot / "bin" / "maipai-bot-host"),
        "run",
        "--data-dir",
        str(data_dir),
        "--hub-url",
        "http://127.0.0.1:9",
        "--voice-port",
        str(voice),
        "--avatar-port",
        str(avatar),
    ]
    process = subprocess.Popen(
        command, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(f"bundle exited early: {stdout.decode()} {stderr.decode()}")
            try:
                with socket.create_connection(("127.0.0.1", voice), timeout=0.25):
                    return
            except OSError:
                time.sleep(0.1)
        pytest.fail("voice listener did not accept a TCP connection within 30 seconds")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.bundle
@pytest.mark.parametrize("platform", ["linux-x64", "linux-arm64"])
def test_linux_bundle_structure_if_built(platform, tmp_path):
    archive = os.environ.get("MAIPAI_BOT_LINUX_BUNDLE")
    archive = (
        Path(archive)
        if archive
        else ROOT
        / "dist"
        / "bot-release"
        / os.environ.get("MAIPAI_BOT_TEST_BUNDLE_TAG", "v0.1.0")
        / f"bot-{platform}.tar.gz"
    )
    if not archive.exists():
        pytest.skip(f"no {platform} bundle was built in this lane")
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        assert names and all(name == "bot" or name.startswith("bot/") for name in names)
        assert all(".." not in Path(name).parts and not Path(name).is_absolute() for name in names)
        tar.extractall(tmp_path, filter="data")
    bot = tmp_path / "bot"
    assert (bot / "bin" / "maipai-bot-host").is_file()
    assert list((bot / "python" / "bin").glob("python3*"))
    site = bot / "app" / "site-packages"
    assert not list(site.glob("reachy_mini*"))
