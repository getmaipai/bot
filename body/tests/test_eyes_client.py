"""The Reachy Eyes serial client, clean-room (docs/dev/eyes-wire-protocol.md).

Every wire string is UNVERIFIED; these tests pin the client's behaviour and
the byte-level ban on anything not in the documented table.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import serial

from maipai_body.bodies.reachy_mini import eyes_client
from maipai_body.bodies.reachy_mini.eyes_client import (
    DEFAULT_PROTOCOL,
    EyesClient,
    next_backoff,
)
from maipai_body.hal.seam import Indicator, Look, Palette
from tests.eyes_fakes import FakeEyesSerial, wait_until

REPO = Path(__file__).resolve().parents[2]
CLIENT_SRC = Path(eyes_client.__file__)

# Written out by hand from the order, independent of the table under test.
DOCUMENTED_WORDS = {"GREEN", "BLUE", "WHITE", "AMBER", "CYAN", "MAGENTA", "INTENSITY", "BLINK"}
BANNED = (
    "RGB",
    "ANIMA",
    "CAPTURE",
    "CFG",
    "ENERGY",
    "SHIMMER",
    "ASYMMETRY",
    "ACK",
    "STARTLE",
    "RED",
)


@pytest.fixture
def pty():
    fake = FakeEyesSerial()
    yield fake
    fake.close()


@pytest.fixture
def make_client():
    made = []

    def build(port, **kw):
        kw.setdefault("base_backoff_s", 0.02)
        kw.setdefault("max_backoff_s", 0.08)
        client = EyesClient(lambda: port, **kw)
        client.start()
        made.append(client)
        return client

    yield build
    for client in made:
        client.close()


def test_client_satisfies_the_indicator_seam(pty, make_client):
    assert isinstance(make_client(pty.path), Indicator)


def test_opens_exclusive_with_50ms_write_timeout_at_115200(pty, make_client):
    client = make_client(pty.path)
    assert wait_until(lambda: client.connected)
    port = client._port
    assert port.exclusive is True
    assert port.write_timeout == 0.05
    assert port.baudrate == 115200
    assert eyes_client.WRITE_TIMEOUT_S == 0.05


def test_colour_and_brightness_bytes(pty, make_client):
    client = make_client(pty.path)
    client.set_look(Look(colour=Palette.CYAN, brightness=0.5))
    assert wait_until(lambda: "INTENSITY 50" in pty.lines())
    assert pty.lines() == ["CYAN", "INTENSITY 50"]


def test_off_is_zero_intensity(pty, make_client):
    client = make_client(pty.path)
    client.off()
    assert wait_until(lambda: pty.lines() == ["INTENSITY 0"])


def test_pulses_and_blinking_switch(pty, make_client):
    client = make_client(pty.path)
    client.pulse("blink")
    client.pulse("ack")
    client.set_blinking(True)
    client.set_blinking(False)
    assert wait_until(lambda: len(pty.lines()) == 5)
    assert pty.lines() == ["BLINK", "BLINK", "BLINK", "BLINK ON", "BLINK OFF"]


def test_unknown_pulse_is_a_value_error_even_when_absent(make_client):
    client = make_client(None)
    with pytest.raises(ValueError):
        client.pulse("startle")  # type: ignore[arg-type]


def test_absent_device_never_raises_and_reports_disconnected(make_client):
    client = make_client(None)
    client.set_look(Look(colour=Palette.GREEN))
    client.pulse("blink")
    client.off()
    assert client.spec().connected is False
    assert not wait_until(lambda: client.connected, timeout_s=0.2)


def test_latest_look_wins_while_disconnected(pty):
    path = {"v": None}
    client = EyesClient(lambda: path["v"], base_backoff_s=0.02, max_backoff_s=0.08)
    client.start()
    try:
        for colour in (Palette.GREEN, Palette.BLUE, Palette.AMBER, Palette.WHITE, Palette.MAGENTA):
            client.set_look(Look(colour=colour, brightness=1.0))
        path["v"] = pty.path
        assert wait_until(lambda: "INTENSITY 100" in pty.lines())
        assert pty.lines() == ["MAGENTA", "INTENSITY 100"]
    finally:
        client.close()


def test_reconnect_replays_the_look_after_a_lost_port(pty, make_client):
    client = make_client(pty.path)
    client.set_look(Look(colour=Palette.AMBER, brightness=0.25))
    assert wait_until(lambda: len(pty.lines()) == 2)
    client._port.close()  # the cable is pulled under the writer
    client.set_look(Look(colour=Palette.BLUE, brightness=0.25))
    assert wait_until(lambda: "BLUE" in pty.lines())
    assert wait_until(lambda: client.connected)
    assert pty.lines()[-2:] == ["BLUE", "INTENSITY 25"]


def test_write_timeout_drops_the_port_and_recovers(pty, make_client):
    client = make_client(pty.path)
    assert wait_until(lambda: client.connected)
    real = client._port
    state = {"failed": 0}

    class Stalled:
        def __getattr__(self, name):
            return getattr(real, name)

        def write(self, data):
            if state["failed"] == 0:
                state["failed"] = 1
                raise serial.SerialTimeoutException("write timeout")
            return real.write(data)

    client._port = Stalled()
    client.set_look(Look(colour=Palette.GREEN))
    assert wait_until(lambda: "GREEN" in pty.lines())
    assert state["failed"] == 1


def test_a_second_client_cannot_open_the_same_port(pty, make_client):
    first = make_client(pty.path)
    assert wait_until(lambda: first.connected)
    second = make_client(pty.path)
    second.set_look(Look(colour=Palette.WHITE))
    assert not wait_until(lambda: second.connected, timeout_s=0.3)
    assert second.spec().connected is False


def test_backoff_doubles_and_caps_at_30_seconds():
    steps = [next_backoff(n) for n in range(12)]
    assert steps[:3] == [0.5, 1.0, 2.0]
    assert max(steps) == 30.0
    assert steps[-1] == 30.0
    assert steps == sorted(steps)


def test_replies_are_drained_not_parsed(pty, make_client):
    client = make_client(pty.path)
    assert wait_until(lambda: client.connected)
    pty.reply(b"hello board\nsecond line\n")
    assert wait_until(lambda: len(client.replies) == 2)
    assert client.replies == ["hello board", "second line"]
    pty.reply(b"x\n" * 5000)
    assert wait_until(lambda: client.replies[-1] == "x")
    assert len(client.replies) <= eyes_client.REPLY_LOG_LINES


def test_only_table_commands_are_ever_written(pty, make_client):
    client = make_client(pty.path)
    for colour in Palette:
        client.set_look(Look(colour=colour, brightness=0.7))
        client.pulse("blink")
        client.pulse("ack")
    client.set_blinking(True)
    client.set_blinking(False)
    client.off()
    assert wait_until(lambda: "BLINK OFF" in pty.lines())
    lines = pty.lines()
    assert "INTENSITY 0" in lines
    for line in lines:
        assert line.split(" ")[0] in DOCUMENTED_WORDS, line
    raw = pty.captured.decode("ascii")
    for word in BANNED:
        assert not re.search(rf"\b{word}", raw), word


def test_the_table_has_no_banned_word_and_no_red():
    table = repr(DEFAULT_PROTOCOL)
    for word in BANNED:
        assert word not in table, word
    assert set(DEFAULT_PROTOCOL.colours.values()) <= DOCUMENTED_WORDS
    assert set(DEFAULT_PROTOCOL.colours) == set(Palette) - {Palette.OFF}


def test_no_vendor_package_constants_or_imports():
    source = CLIENT_SRC.read_text()
    for pattern in (r"\b0\.87\b", r"\b0\.42\b", r"\b0\.4\b", r"\b0\.1\b", r"reachy_eyes"):
        assert not re.search(pattern, source), pattern
    for path in (REPO / "body" / "pyproject.toml", REPO / "body" / "uv.lock"):
        text = path.read_text().lower()
        assert "reachy_eyes" not in text and "reachy-eyes" not in text, path
    for py in (REPO / "body" / "maipai_body").rglob("*.py"):
        assert "import reachy_eyes" not in py.read_text(), py
        assert "from reachy_eyes" not in py.read_text(), py


def _probe(*args: str) -> subprocess.CompletedProcess[str]:
    probe = REPO / "scripts" / "probe_eyes.py"
    return subprocess.run(
        [sys.executable, str(probe), *args], capture_output=True, text=True, timeout=20
    )


def test_probe_sends_nothing_by_default_and_only_table_commands(pty):
    quiet = _probe("--port", pty.path, "--listen", "0.2")
    assert quiet.returncode == 0, quiet.stderr
    assert pty.lines() == []
    sent = _probe("--port", pty.path, "--listen", "0.1", "--send", "blink")
    assert sent.returncode == 0, sent.stderr
    assert pty.lines() == ["BLINK"]
    refused = _probe("--port", pty.path, "--send", "rgb")
    assert refused.returncode != 0
    assert pty.lines() == ["BLINK"]
