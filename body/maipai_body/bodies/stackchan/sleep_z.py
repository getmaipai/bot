"""Version-gated host wrapper for the future StackChan sleep Z tool."""

from __future__ import annotations

from collections.abc import Callable

from .expression_map import version_at_least

SLEEP_Z_FIRMWARE: tuple[int, int, int] | None = None


class SleepZ:
    def __init__(self, call_tool: Callable[[str, dict], object], firmware_version) -> None:
        self._call_tool = call_tool
        self._firmware_version = firmware_version

    def _stage(self, stage: int) -> None:
        if SLEEP_Z_FIRMWARE is not None and version_at_least(
            self._firmware_version()
            if callable(self._firmware_version)
            else self._firmware_version,
            SLEEP_Z_FIRMWARE,
        ):
            self._call_tool("self.face.sleep_z", {"stage": stage})

    def drowsy(self) -> None:
        self._stage(1)

    def asleep(self) -> None:
        self._stage(2)

    def off(self) -> None:
        self._stage(0)
