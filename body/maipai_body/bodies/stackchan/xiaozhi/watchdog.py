"""A cheap watch on a StackChan that is connected but does not answer.

On 2026-10-21 the unit sat connected and silent for 20 minutes and the host logged nothing about
it; on 2026-11-12 it kept answering one call in three for three minutes and the watch never
started its clock, because any answer reset it. The watch now keeps a sliding window (120 s) of
tool-call outcomes, the two ages (the last audio frame and the last frame of any kind from the
unit) and the time since the last answer.

* Warn (one WARNING, at most once a minute): the window holds ``warn_timeouts`` or more timeouts
  and more timeouts than answers.
* Act: that has held for ``hold_s`` (two windows from the first sign), or no call has been answered
  for ``no_answer_s`` while calls keep timing out. The unit is asked to restart itself (the xiaozhi
  ``system`` ``reboot`` command), at most once per ``reboot_every_s``. The firmware refuses a
  fourth restart in an hour (the self-restart guard) and the host stops asking while it says so.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable

LOG = logging.getLogger("maipai_body.bodies.stackchan.xiaozhi.watchdog")


class DeviceWatchdog:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        window_s: float = 120.0,
        warn_timeouts: int = 6,
        hold_s: float = 120.0,
        no_answer_s: float = 60.0,
        reboot_every_s: float = 600.0,
        reboot: Callable[[], object] | None = None,
    ) -> None:
        self._clock = clock
        self._window_s = window_s
        self._warn_timeouts = warn_timeouts
        self._hold_s = hold_s
        self._no_answer_s = no_answer_s
        self._reboot_every_s = reboot_every_s
        self.reboot = reboot
        self._last_audio_at: float | None = None
        self._last_message_at: float | None = None
        self._outcomes: deque[tuple[float, bool]] = deque()
        self._last_answer_at: float | None = None
        self._first_timeout_at: float | None = None  # the start of the current run of trouble
        self._bad_since: float | None = None
        self._last_warned_at = float("-inf")
        self._last_reboot_at = float("-inf")

    def note_message(self, *, audio: bool) -> None:
        """A frame arrived from the unit."""
        now = self._clock()
        self._last_message_at = now
        if audio:
            self._last_audio_at = now

    def _reset(self) -> None:
        self._outcomes.clear()
        self._first_timeout_at = None
        self._bad_since = None

    def note_tool(self, ok: bool, *, socket_open: bool = True) -> None:
        """A tool call finished: ``ok`` False means the unit did not answer it in time."""
        now = self._clock()
        if not socket_open:
            self._reset()
            return
        self._outcomes.append((now, ok))
        while self._outcomes and now - self._outcomes[0][0] > self._window_s:
            self._outcomes.popleft()
        if ok:
            self._last_answer_at = now
            self._first_timeout_at = None
        elif self._first_timeout_at is None:
            self._first_timeout_at = now
        timeouts = sum(1 for _, fine in self._outcomes if not fine)
        answers = len(self._outcomes) - timeouts
        troubled = timeouts >= self._warn_timeouts and timeouts > answers
        if not troubled:
            self._bad_since = None
        elif self._bad_since is None:
            self._bad_since = now
        if troubled and now - self._last_warned_at >= 60.0:
            self._last_warned_at = now
            LOG.warning(
                "StackChan has not answered tool calls reliably: %d timed out and %d answered in "
                "the last %.0f s while its socket is open (last audio frame %s ago, last message "
                "from the unit %s ago)",
                timeouts,
                answers,
                self._window_s,
                self._age(self._last_audio_at, now),
                self._age(self._last_message_at, now),
            )
        silent_for = 0.0
        if not ok and self._first_timeout_at is not None:
            since = max(self._first_timeout_at, self._last_answer_at or self._first_timeout_at)
            silent_for = now - since
        stuck = troubled and self._bad_since is not None and now - self._bad_since >= self._hold_s
        if (
            (stuck or silent_for >= self._no_answer_s)
            and self.reboot is not None
            and now - self._last_reboot_at >= self._reboot_every_s
        ):
            self._last_reboot_at = now
            LOG.warning(
                "StackChan self-heal: restart requested (%d timeouts and %d answers in %.0f s, "
                "%.0f s since an answer)",
                timeouts,
                answers,
                self._window_s,
                silent_for,
            )
            try:
                self.reboot()
            except Exception:
                LOG.warning("StackChan restart request failed", exc_info=True)

    @staticmethod
    def _age(stamp: float | None, now: float) -> str:
        return "never" if stamp is None else f"{now - stamp:.0f} s"
