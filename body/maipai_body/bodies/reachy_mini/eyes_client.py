"""Reachy Eyes USB serial client (EYES-03), written clean-room.

Source of every fact here is docs/dev/eyes-wire-protocol.md: the public
README as summarised to us and our own notes. No vendor source, firmware,
default or tuned value was read, and no vendor module is imported. The wire
lines are UNVERIFIED data in ``WireProtocol``; the owner's unit settles them
by editing that one table. Nothing outside the table is ever written.

One writer thread owns the port. Callers enqueue and return at once, the
latest look wins, and a lost port reconnects with a capped backoff. Never
raises ``BodyLost``: an absent or unplugged board reports
``connected=False``.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import serial
from serial.tools import list_ports

from maipai_body.hal.seam import (
    PULSE_NAMES,
    IndicatorSpec,
    Look,
    Palette,
    PulseName,
    check_pulse,
)

WRITE_TIMEOUT_S = 0.05
BACKOFF_BASE_S = 0.5
BACKOFF_CAP_S = 30.0
REPLY_LOG_LINES = 64
_PENDING_PULSES = 16
_PARTIAL_REPLY_CHARS = 4096
_IDLE_DRAIN_S = 0.05

# Design-note ids, confirmed with lsusb on the unit at arrival (see
# scripts/udev/reachy-eyes-setup.sh).
EYES_USB_VID = 0x2E8A
EYES_USB_PID = 0x10FC


@dataclass(frozen=True)
class WireProtocol:
    """The commands as data. Every string is UNVERIFIED (see the note)."""

    baud: int = 115200
    terminator: bytes = b"\n"
    colours: dict[Palette, str] = field(
        default_factory=lambda: {
            Palette.WHITE: "WHITE",
            Palette.GREEN: "GREEN",
            Palette.BLUE: "BLUE",
            Palette.AMBER: "AMBER",
            Palette.CYAN: "CYAN",
            Palette.MAGENTA: "MAGENTA",
        }
    )
    intensity: str = "INTENSITY {percent}"
    blink: str = "BLINK"
    blink_enable: str = "BLINK ON"
    blink_disable: str = "BLINK OFF"

    def encode(self, line: str) -> bytes:
        return line.encode("ascii") + self.terminator

    def intensity_line(self, brightness: float) -> str:
        return self.intensity.format(percent=round(max(0.0, min(1.0, brightness)) * 100))

    def look_lines(self, look: Look) -> tuple[str, ...]:
        """Wire lines for a steady look. Off has no colour line of its own."""
        if look.colour is Palette.OFF:
            return (self.intensity_line(0.0),)
        return (self.colours[look.colour], self.intensity_line(look.brightness))

    def named_commands(self) -> dict[str, str]:
        """Every line the probe may send, by a short name."""
        named = {name.value: line for name, line in self.colours.items()}
        named["blink"] = self.blink
        named["blink-enable"] = self.blink_enable
        named["blink-disable"] = self.blink_disable
        named["intensity-off"] = self.intensity_line(0.0)
        named["intensity-full"] = self.intensity_line(1.0)
        return named


DEFAULT_PROTOCOL = WireProtocol()


def next_backoff(
    attempt: int, base_s: float = BACKOFF_BASE_S, cap_s: float = BACKOFF_CAP_S
) -> float:
    """Reconnect delay after ``attempt`` failures: doubling, capped."""
    return min(cap_s, base_s * (2 ** min(attempt, 30)))


def find_eyes_port() -> str | None:
    """The device path of the board by USB ids, or ``None`` when absent."""
    for info in list_ports.comports():
        if info.vid == EYES_USB_VID and info.pid == EYES_USB_PID:
            return info.device
    return None


def open_serial(path: str, protocol: WireProtocol = DEFAULT_PROTOCOL) -> Any:
    """Open the port exclusively with the 50 ms write timeout."""
    return serial.Serial(
        path, protocol.baud, timeout=0, write_timeout=WRITE_TIMEOUT_S, exclusive=True
    )


class EyesClient:
    """``Indicator`` over USB serial. Call ``start`` once, ``close`` at the end."""

    def __init__(
        self,
        find_port: Callable[[], str | None] = find_eyes_port,
        *,
        protocol: WireProtocol = DEFAULT_PROTOCOL,
        opener: Callable[[str, WireProtocol], Any] = open_serial,
        base_backoff_s: float = BACKOFF_BASE_S,
        max_backoff_s: float = BACKOFF_CAP_S,
    ) -> None:
        self._find_port = find_port
        self._protocol = protocol
        self._opener = opener
        self._base_backoff_s = base_backoff_s
        self._max_backoff_s = max_backoff_s
        self._cond = threading.Condition()
        self._look_lines: tuple[str, ...] | None = None
        self._look_dirty = False
        self._pulses: deque[str] = deque(maxlen=_PENDING_PULSES)
        self._replies: deque[str] = deque(maxlen=REPLY_LOG_LINES)
        self._partial = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._port: Any = None

    # -- the seam -------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._port is not None

    @property
    def replies(self) -> list[str]:
        with self._cond:
            return list(self._replies)

    def spec(self) -> IndicatorSpec:
        return IndicatorSpec(
            connected=self.connected, palette=list(Palette), pulses=list(PULSE_NAMES)
        )

    def set_look(self, look: Look) -> None:
        self._set_look_lines(self._protocol.look_lines(look))

    def pulse(self, name: PulseName) -> None:
        check_pulse(name)
        # The seam's ack has no cited wire command: it is two blinks.
        lines = (self._protocol.blink,) * (2 if name == "ack" else 1)
        self._enqueue(*lines)

    def off(self) -> None:
        self._set_look_lines(self._protocol.look_lines(Look(colour=Palette.OFF, brightness=0.0)))

    def set_blinking(self, enabled: bool) -> None:
        self._enqueue(self._protocol.blink_enable if enabled else self._protocol.blink_disable)

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="eyes-writer", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # -- internals ------------------------------------------------------

    def _set_look_lines(self, lines: tuple[str, ...]) -> None:
        with self._cond:
            if lines == self._look_lines and not self._look_dirty:
                return
            self._look_lines = lines
            self._look_dirty = True
            self._cond.notify()

    def _enqueue(self, *lines: str) -> None:
        with self._cond:
            self._pulses.extend(lines)
            self._cond.notify()

    def _try_open(self) -> bool:
        try:
            path = self._find_port()
            if path is None:
                return False
            self._port = self._opener(path, self._protocol)
        except (serial.SerialException, OSError, ValueError):
            self._port = None
            return False
        with self._cond:
            # A fresh connection replays the wanted look.
            self._look_dirty = self._look_lines is not None
        return True

    def _drop(self) -> None:
        port, self._port = self._port, None
        try:
            if port is not None:
                port.close()
        except (serial.SerialException, OSError):
            pass
        with self._cond:
            self._pulses.clear()
            self._look_dirty = self._look_lines is not None
            self._partial = ""

    def _drain(self) -> None:
        waiting = self._port.in_waiting
        if not waiting:
            return
        data = self._port.read(waiting).decode("ascii", errors="replace")
        with self._cond:
            text = (self._partial + data).replace("\r", "")
            *whole, self._partial = text.split("\n")
            self._partial = self._partial[-_PARTIAL_REPLY_CHARS:]
            self._replies.extend(line for line in whole if line)

    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            if self._port is None:
                if not self._try_open():
                    with self._cond:
                        self._pulses.clear()
                    delay = next_backoff(attempt, self._base_backoff_s, self._max_backoff_s)
                    attempt += 1
                    self._stop.wait(delay)
                    continue
                attempt = 0
            with self._cond:
                if not (self._look_dirty or self._pulses):
                    self._cond.wait(_IDLE_DRAIN_S)
                look = self._look_lines if self._look_dirty else None
                self._look_dirty = False
                pulses = list(self._pulses)
                self._pulses.clear()
            try:
                for line in (*(look or ()), *pulses):
                    self._port.write(self._protocol.encode(line))
                self._drain()
            except (serial.SerialException, OSError):
                self._drop()
        self._drop()
