"""StackChan stays still while charging (owner request 2026-10-20).

``PowerIdle`` drives the firmware ``set_idle_motion`` tool from the three
answers that all mean "no idle movement": the unit is on USB power, night
is active, or the configured ``robot.idle.level`` is ``still``. The robot
wants idle motion enabled (``set_idle_motion(True)``) exactly when none of
those hold, so on battery the configured level applies again by itself.

A failing write is logged at most once a minute and retried on the next
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
        """True while the robot must not wander: charging, night, or level still."""
        if self._charging:
            return True
        if self._night_active():
            return True
        return self._configured_level() == "still"

    def on_battery_status(self, charging: bool) -> None:
        """Record a battery reading (charging on or off) and re-evaluate the motion."""
        self._charging = charging
        self.refresh()

    def refresh(self) -> None:
        """Re-evaluate the wanted idle-motion value and write it if it changed."""
        wanted = not self.still
        current = self._applied if self._applied is not None else True
        if wanted != current:
            self._write(wanted)

    def _write(self, value: bool) -> None:
        try:
            self._set_idle_motion(value)
        except Exception:
            now = self._clock()
            if now - self._last_failure_warn >= FAILURE_WARN_S:
                logger.warning("power idle motion write failed", exc_info=True)
                self._last_failure_warn = now
            return
        self._applied = value
