"""A pty standing in for the Reachy Eyes USB serial port.

The client opens ``path`` with real pyserial, so exclusivity, the write
timeout and raw bytes are exercised for real; the test reads what the client
wrote from the master side and plays device replies into it.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable


class FakeEyesSerial:
    def __init__(self) -> None:
        self._master, self._slave = os.openpty()
        os.set_blocking(self._master, False)
        self.path = os.ttyname(self._slave)
        self.captured = b""

    def pump(self) -> bytes:
        """Move whatever the client wrote into ``captured`` and return it."""
        chunks = []
        while True:
            try:
                data = os.read(self._master, 4096)
            except (BlockingIOError, OSError):
                break
            if not data:
                break
            chunks.append(data)
        got = b"".join(chunks)
        self.captured += got
        return got

    def lines(self) -> list[str]:
        self.pump()
        return [ln for ln in self.captured.decode("ascii").split("\n") if ln]

    def reply(self, data: bytes) -> None:
        os.write(self._master, data)

    def close(self) -> None:
        for fd in (self._master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass


def wait_until(predicate: Callable[[], bool], timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()
