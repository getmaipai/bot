"""A cheap watch on a StackChan that is connected but does not answer.

On 2026-10-21 the unit sat connected and silent for 20 minutes and the host logged nothing about
it. This keeps two ages (the last audio frame and the last frame of any kind from the unit) and the
time since its tool calls started failing. After ``warn_after_s`` of failures with the socket open
it logs one WARNING with both ages, so the log says whether the unit went quiet or only stopped
answering. After ``reboot_after_s`` it asks the unit to restart itself (the xiaozhi ``system``
``reboot`` command), at most once per ``reboot_every_s``, so nobody has to power-cycle it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

LOG = logging.getLogger("maipai_body.bodies.stackchan.xiaozhi.watchdog")


class DeviceWatchdog:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        warn_after_s: float = 60.0,
        reboot_after_s: float = 120.0,
        reboot_every_s: float = 600.0,
        reboot: Callable[[], object] | None = None,
    ) -> None:
        self._clock = clock
        self._warn_after_s = warn_after_s
        self._reboot_after_s = reboot_after_s
        self._reboot_every_s = reboot_every_s
        self.reboot = reboot
        self._last_audio_at: float | None = None
        self._last_message_at: float | None = None
        self._failing_since: float | None = None
        self._last_warned_at = float("-inf")
        self._last_reboot_at = float("-inf")

    def note_message(self, *, audio: bool) -> None:
        """A frame arrived from the unit."""
        now = self._clock()
        self._last_message_at = now
        if audio:
            self._last_audio_at = now

    def note_tool(self, ok: bool, *, socket_open: bool = True) -> None:
        """A tool call finished: ``ok`` False means the unit did not answer it in time."""
        now = self._clock()
        if ok or not socket_open:
            self._failing_since = None
            return
        if self._failing_since is None:
            self._failing_since = now
            return
        failing_for = now - self._failing_since
        if failing_for >= self._warn_after_s and now - self._last_warned_at >= 60.0:
            self._last_warned_at = now
            LOG.warning(
                "StackChan has not answered tool calls for %.0f s while its socket is open "
                "(last audio frame %s ago, last message from the unit %s ago)",
                failing_for,
                self._age(self._last_audio_at, now),
                self._age(self._last_message_at, now),
            )
        if (
            failing_for >= self._reboot_after_s
            and self.reboot is not None
            and now - self._last_reboot_at >= self._reboot_every_s
        ):
            self._last_reboot_at = now
            LOG.warning(
                "StackChan has not answered for %.0f s; asking it to restart itself", failing_for
            )
            try:
                self.reboot()
            except Exception:
                LOG.warning("StackChan restart request failed", exc_info=True)

    @staticmethod
    def _age(stamp: float | None, now: float) -> str:
        return "never" if stamp is None else f"{now - stamp:.0f} s"
