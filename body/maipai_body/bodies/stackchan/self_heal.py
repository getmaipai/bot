"""StackChan self-healing on the host (design note docs/dev/stackchan-self-healing-2026-11-13.md).

Three small pieces with no sockets, driven by their callers:

* ``SelfHealState``: what the unit reports about its own restart guard (patch 085: at most three
  self-restarts an hour), its microphone level and whether it is muted. The host stops asking for
  restarts while the unit holds, and the ring shows the existing fault look.
* ``WakeSelfTest`` (rung (c)): the schedule of the wake engine's injection test (patch 086). A miss
  rebuilds the engine in place and tests again; a second miss asks for a restart. A muted unit is
  never treated as deaf, and a test the unit skipped (busy) or never answered counts as nothing.
* ``CameraStallWatch`` (rung (d)): a camera that streamed and then went quiet for 60 s with the unit
  idle and watching on is asked again three times, then its avatar socket is closed so it
  reconnects, then a restart is requested.

Every recovery logs one INFO line, ``StackChan self-heal: <what> (<why>)``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping

LOG = logging.getLogger("maipai_body.bodies.stackchan.self_heal")


def _flag(value: object) -> bool:
    return value is True or (isinstance(value, int) and not isinstance(value, bool) and value != 0)


class SelfHealState:
    """The newest guard, mute and microphone facts the unit reported."""

    def __init__(self, on_hold: Callable[[bool], object] | None = None) -> None:
        self.on_hold = on_hold
        self.hold = False
        self.muted = False
        self.restarts: int | None = None
        self.mic_rms_max: int | None = None

    def observe(self, kind: str, extra: Mapping[str, object] | None) -> None:
        extra = extra or {}
        if kind in {"wake_stats", "boot"}:
            if "heal_n" in extra and isinstance(extra["heal_n"], int):
                self.restarts = extra["heal_n"]
            if "heal_hold" in extra:
                hold = _flag(extra["heal_hold"])
                if hold != self.hold:
                    self.hold = hold
                    LOG.info(
                        "StackChan self-heal: restart hold %s (%s self-restarts this hour)",
                        "on, the host stops asking" if hold else "off",
                        self.restarts if self.restarts is not None else "?",
                    )
                    if self.on_hold is not None:
                        try:
                            self.on_hold(hold)
                        except Exception:
                            LOG.warning("StackChan hold light failed", exc_info=True)
            if "muted" in extra:
                # Full quiet turns the microphone off exactly as mute does: not a deaf robot either.
                self.muted = _flag(extra["muted"]) or _flag(extra.get("quiet"))
            mic = extra.get("mic_rms_max")
            if isinstance(mic, int) and not isinstance(mic, bool):
                self.mic_rms_max = mic
            why = extra.get("heal_why")
            if kind == "boot" and isinstance(why, str) and why:
                LOG.info(
                    "StackChan self-heal: the unit restarted itself (%s), %s so far this hour",
                    why,
                    self.restarts if self.restarts is not None else "?",
                )
        elif kind == "heal":
            action, why, count = extra.get("action"), extra.get("why"), extra.get("n")
            if action == "refused":
                LOG.warning(
                    "StackChan self-heal: restart refused (%s): %s self-restarts this hour already",
                    why,
                    count,
                )
            else:
                LOG.info(
                    "StackChan self-heal: the unit is restarting (%s), %s this hour", why, count
                )


class WakeSelfTest:
    """When to run the wake engine test, and what to do with its answer.

    ``tick()`` returns the system commands to send now (``wake_selftest``, ``wake_rebuild``,
    ``reboot``); ``on_event`` takes the unit's ``wake_selftest`` events (from another thread).
    """

    def __init__(
        self,
        state: SelfHealState,
        *,
        clock: Callable[[], float] = time.monotonic,
        is_idle: Callable[[], bool] = lambda: True,
        is_connected: Callable[[], bool] = lambda: True,
        first_after_s: float = 300.0,
        after_turn_s: float = 60.0,
        every_s: float = 3600.0,
        wait_s: float = 15.0,
        retest_s: float = 5.0,
        after_restart_s: float = 300.0,
    ) -> None:
        self._state = state
        self._clock = clock
        self._is_idle = is_idle
        self._is_connected = is_connected
        self._after_turn_s = after_turn_s
        self._every_s = every_s
        self._wait_s = wait_s
        self._retest_s = retest_s
        self._after_restart_s = after_restart_s
        self._lock = threading.Lock()
        self._next_at = clock() + first_after_s
        self._awaiting_since: float | None = None
        self._fails = 0
        self._outbox: list[str] = []

    def note_turn_end(self) -> None:
        """A turn ended: test the engine a minute later (idle only)."""
        with self._lock:
            self._next_at = self._clock() + self._after_turn_s

    def tick(self) -> list[str]:
        now = self._clock()
        with self._lock:
            if self._outbox:
                out, self._outbox = self._outbox, []
                return out
            if self._awaiting_since is not None:
                if now - self._awaiting_since >= self._wait_s:
                    # No answer at all: neither a pass nor a fail, ask again in a minute.
                    self._next_at = self._awaiting_since + 60.0
                    self._awaiting_since = None
                return []
            if now < self._next_at:
                return []
            if (
                not self._is_connected()
                or not self._is_idle()
                or self._state.muted
                or self._state.hold
            ):
                return []  # stays due until the unit is idle, unmuted and free to restart
            self._awaiting_since = now
            return ["wake_selftest"]

    def on_event(self, kind: str, extra: Mapping[str, object] | None) -> None:
        if kind != "wake_selftest":
            return
        result = (extra or {}).get("result")
        now = self._clock()
        with self._lock:
            if result == "hit":
                if self._fails:
                    LOG.info(
                        "StackChan self-heal: the wake engine recovered after a rebuild "
                        "(it heard its own test clip)"
                    )
                self._fails = 0
                self._awaiting_since = None
                self._next_at = now + self._every_s
            elif result == "miss":
                self._awaiting_since = None
                self._fails += 1
                if self._fails == 1:
                    LOG.warning(
                        "StackChan self-heal: the wake engine missed its own test clip; "
                        "rebuilding it and testing again"
                    )
                    self._outbox.append("wake_rebuild")
                    self._next_at = now + self._retest_s
                else:
                    LOG.warning(
                        "StackChan self-heal: the wake engine missed its test clip again after "
                        "a rebuild; asking the unit to restart"
                    )
                    self._fails = 0
                    self._outbox.append("reboot")
                    self._next_at = now + self._after_restart_s
            elif result == "skipped":
                self._awaiting_since = None
                self._next_at = now + 60.0


class CameraStallWatch:
    """The camera ladder: re-ask three times, then reconnect the avatar socket, then restart."""

    def __init__(self, *, quiet_s: float = 60.0, reasks: int = 3) -> None:
        self._quiet_s = quiet_s
        self._reasks = reasks
        self._quiet_since: float | None = None  # None until the stream has delivered a frame
        self._stage = 0

    def note_frame(self, now: float) -> None:
        self._quiet_since = now
        self._stage = 0

    def step(self, now: float, *, watching: bool, idle: bool) -> str | None:
        """``reask``, ``reconnect``, ``restart`` or None. Watching off or a busy unit (the unit
        pauses the stream in a turn on purpose) only restarts the wait."""
        if self._quiet_since is None:
            return None  # never streamed: the connect-time retry owns that case
        if not watching or not idle:
            self._quiet_since = now
            return None
        if now - self._quiet_since < self._quiet_s:
            return None
        self._quiet_since = now
        if self._stage < self._reasks:
            self._stage += 1
            return "reask"
        if self._stage == self._reasks:
            self._stage += 1
            return "reconnect"
        self._stage = 0
        return "restart"
