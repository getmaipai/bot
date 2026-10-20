"""StackChan stays still while charging (owner request 2026-10-20).

``PowerIdle`` drives the firmware ``set_idle_motion`` tool from the three
answers that all mean "no idle movement": the unit is on USB power, night
is active, or the configured ``robot.idle.level`` is ``still``. The robot
wants idle motion enabled (``set_idle_motion(True)``) exactly when none of
those hold, so on battery the configured level applies again by itself.

Unknown is still (fail safe): until the unit has positively reported that it
is on battery, and again when its last good reading is older than
``STATUS_TTL_S``, the robot does not move on its own. A failing write is logged
at most once a minute and retried (after ``RETRY_S``) on the next ``tick()``,
battery status or ``refresh()`` call, so a failed write is never lost.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

logger = logging.getLogger("maipai_body.bodies.stackchan.power_idle")

# A failed set_idle_motion write is logged at most this often (the same
# one-minute cap the light wiring uses for a failed battery read).
FAILURE_WARN_S = 60.0
# A battery reading older than this counts as unknown (the unit may have been plugged in).
STATUS_TTL_S = 180.0
# Wait this long before retrying a failed idle-motion write.
RETRY_S = 5.0


class PowerIdle:
    """Keep the StackChan idle-motion tool matched to "may it move?".

    ``set_idle_motion`` is the firmware tool call (the adapter's
    ``set_idle_motion``); ``night_active`` and ``configured_level`` are
    callables so the night rule and the owner's ``robot.idle.level`` stay
    injected. The wanted idle-motion value is ``not self.still``; a write
    goes out only when it differs from the last value actually applied.
    """

    def __init__(
        self,
        set_idle_motion: Callable[[bool], object],
        *,
        night_active: Callable[[], bool] = lambda: False,
        configured_level: Callable[[], str] = lambda: "calm",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._set_idle_motion = set_idle_motion
        self._night_active = night_active
        self._configured_level = configured_level
        self._clock = clock
        self._charging = False
        self._last_ok: float | None = None  # when the unit last answered a battery read
        self._next_try = float("-inf")
        # The last value successfully written. None means the device is still
        # at its default (calm, motion on) because it was never plugged in.
        self._applied: bool | None = None
        self._last_failure_warn = float("-inf")

    @property
    def charging(self) -> bool:
        """True once a charging reading has been told to us."""
        return self._charging

    @property
    def still(self) -> bool:
        """True while the robot must not wander: unknown power, charging, night, or level still."""
        if self._charging or not self._power_known():
            return True
        if self._night_active():
            return True
        return self._configured_level() == "still"

    def _power_known(self) -> bool:
        return self._last_ok is not None and self._clock() - self._last_ok < STATUS_TTL_S

    def on_battery_status(self, charging: bool) -> None:
        """Record a battery reading (charging on or off) and re-evaluate the motion."""
        self._charging = charging
        self._last_ok = self._clock()
        self._next_try = float("-inf")
        self.refresh()

    def tick(self) -> None:
        """Call about every second: an unknown or stale power state turns idle motion off."""
        if self._clock() >= self._next_try:
            self.refresh()

    def refresh(self) -> None:
        """Re-evaluate the wanted idle-motion value and write it if it changed."""
        wanted = not self.still
        current = self._applied if self._applied is not None else True
        if wanted != current:
            self._write(wanted)

    def _write(self, value: bool) -> None:
        now = self._clock()
        try:
            self._set_idle_motion(value)
        except Exception:
            if now - self._last_failure_warn >= FAILURE_WARN_S:
                logger.warning("power idle motion write failed", exc_info=True)
                self._last_failure_warn = now
            self._next_try = now + RETRY_S
            return
        self._applied = value
