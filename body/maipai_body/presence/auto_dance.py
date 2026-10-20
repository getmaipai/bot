"""BOT-SC-DANCE-01 (host half): the pure dance start/stop policy.

Decides when the body dances to detected music, given a per-tick
``music`` boolean (from ``speech/music.py``), an active conversation
turn, and the quiet-hours flag. Pure: the clock is injected through
:meth:`AutoDancePolicy.update`, nothing reads a real clock, and the
policy owns no audio of its own - it only sees the boolean.

Every duration is an UNMEASURED design default: start after 3.0 s of
music, dance for 10.0 s, re-arm after 10.0 s of quiet. The 1.0 s gap
tolerance is the same kind of guess, sized so a single missed tick or a
brief detector dip does not cancel a run that is already in flight.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

MUSIC_GAP_TOLERANCE_S = 1.0


class AutoDancePolicy:
    """Pure start/stop policy for dancing to detected music.

    Feed one :meth:`update` per tick with the injected clock. The
    policy answers ``"start"`` exactly once per dance (when music has
    been continuously true, gaps under 1.0 s excepted, for
    ``start_after_s``), then ``"stop"`` exactly once either
    ``dance_for_s`` later or the instant a turn becomes active or the
    policy becomes disabled or quiet hours engage. After a stop it sits
    in cooldown and will not start again until music has been false
    continuously for ``quiet_before_rearm_s`` - so continuous music
    after a dance never restarts it, and ten seconds of silence does.
    """

    def __init__(
        self,
        *,
        enabled: Callable[[], bool] = lambda: False,
        start_after_s: float = 3.0,
        dance_for_s: float = 10.0,
        quiet_before_rearm_s: float = 10.0,
        music_gap_tolerance_s: float = MUSIC_GAP_TOLERANCE_S,
    ) -> None:
        self._enabled = enabled
        self._start_after_s = start_after_s
        self._dance_for_s = dance_for_s
        self._quiet_before_rearm_s = quiet_before_rearm_s
        self._music_gap_tolerance_s = music_gap_tolerance_s
        self._dancing = False
        self._danced_since: float | None = None
        self._state: Literal["idle", "cooldown"] = "idle"
        self._music_run_since: float | None = None
        self._last_music_true: float | None = None
        self._quiet_since: float | None = None

    @property
    def dancing(self) -> bool:
        """Whether a dance is currently in progress."""
        return self._dancing

    def update(
        self,
        now: float,
        *,
        music: bool,
        turn_active: bool,
        quiet_hours_active: bool = False,
    ) -> Literal["start", "stop", "none"]:
        """Advance the policy by one tick at injected time ``now``."""
        blocked = turn_active or quiet_hours_active or not self._enabled()

        if self._dancing:
            elapsed = now - (self._danced_since if self._danced_since is not None else now)
            if blocked or elapsed >= self._dance_for_s:
                self._stop(now, music)
                return "stop"
            return "none"

        if blocked:
            # a blocked tick can never start, and it resets any run in
            # flight: a conversation or quiet hours is a real interruption
            self._music_run_since = None
            self._last_music_true = None
            self._quiet_since = None
            return "none"

        if self._state == "cooldown":
            if music:
                # the re-arm clock needs continuous silence; also, a run
                # must be re-earned from scratch after a re-arm
                self._quiet_since = None
                self._music_run_since = None
                self._last_music_true = None
            elif self._quiet_since is None:
                self._quiet_since = now
            elif now - self._quiet_since >= self._quiet_before_rearm_s:
                self._state = "idle"
                self._quiet_since = None
                self._last_music_true = None
            return "none"

        if music:
            gap_reset = (
                self._last_music_true is None
                or now - self._last_music_true >= self._music_gap_tolerance_s
            )
            if gap_reset:
                self._music_run_since = now
            self._last_music_true = now
            if (
                self._music_run_since is not None
                and now - self._music_run_since >= self._start_after_s
            ):
                self._dancing = True
                self._danced_since = now
                return "start"
        elif (
            self._music_run_since is not None
            and self._last_music_true is not None
            and now - self._last_music_true >= self._music_gap_tolerance_s
        ):
            self._music_run_since = None
            self._last_music_true = None
        return "none"

    def _stop(self, now: float, music: bool) -> None:
        self._dancing = False
        self._danced_since = None
        self._state = "cooldown"
        self._music_run_since = None
        self._last_music_true = None
        self._quiet_since = None if music else now
