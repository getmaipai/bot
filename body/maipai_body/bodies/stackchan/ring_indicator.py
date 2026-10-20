"""The StackChan ring indicator: the Indicator the 12-pixel ring answers.

docs/dev/led-standard-2026-10-20.md: the whole-ring ``set_led_color`` is
the only colour call the ring takes (one colour, one call), the styles are
driven by the host timer (a caller's ``tick()`` about every 50 ms), and
the colour numbers live in ``ring.py``. The indicator never raises
``BodyLost``: a failing ``write`` is logged, at most once a second, and
swallowed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from maipai_body.bodies.stackchan.ring import ring_rgb
from maipai_body.hal.seam import (
    PULSE_NAMES,
    IndicatorSpec,
    Look,
    LookStyle,
    Palette,
    PulseName,
    check_pulse,
)

logger = logging.getLogger("maipai_body.bodies.stackchan.ring_indicator")

PULSE_S = 0.15
# The pulse's white at 0.5 brightness, precomputed: the flash is a fixed
# colour, independent of whatever look it interrupts.
PULSE_RGB = ring_rgb(Look(colour=Palette.WHITE, brightness=0.5), 0.0, 0.0)


class StackChanRingIndicator:
    """Drives the 12-pixel ring from the seam's looks (docs/dev/led-standard-2026-10-20.md).

    ``write`` is the device's whole-ring colour call (the client's
    ``set_led_color``); a test passes a recorder instead. ``set_look``
    writes the look's t=0 colour at once and starts its style clock;
    ``tick()`` advances an animated look and writes only a changed colour.
    """

    def __init__(
        self,
        write: Callable[[tuple[int, int, int]], object],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._write = write
        self._clock = clock
        self._look: Look | None = None
        self._look_started = 0.0
        self._pulse_until: float | None = None
        self._last: tuple[int, int, int] | None = None
        self._last_write_error = float("-inf")

    def spec(self) -> IndicatorSpec:
        return IndicatorSpec(
            connected=True,
            palette=[colour for colour in Palette if colour is not Palette.OFF],
            pulses=list(PULSE_NAMES),
        )

    def set_look(self, look: Look) -> None:
        if look == self._look:
            return
        self._look = look
        self._look_started = self._clock()
        self._pulse_until = None
        self._send(ring_rgb(look, look.period_s, 0.0))

    def tick(self) -> None:
        now = self._clock()
        if self._pulse_until is not None:
            if now < self._pulse_until:
                colour = PULSE_RGB
            else:
                self._pulse_until = None
                colour = self._look_colour(now)
        else:
            if self._look is None or self._look.style is LookStyle.STEADY:
                return
            colour = self._look_colour(now)
        if colour != self._last:
            self._send(colour)

    def pulse(self, name: PulseName) -> None:
        check_pulse(name)
        self._pulse_until = self._clock() + PULSE_S
        self._send(PULSE_RGB)

    def off(self) -> None:
        self._look = None
        self._pulse_until = None
        self._send((0, 0, 0))

    def _look_colour(self, now: float) -> tuple[int, int, int]:
        if self._look is None:
            return (0, 0, 0)
        return ring_rgb(self._look, self._look.period_s, now - self._look_started)

    def _send(self, rgb: tuple[int, int, int]) -> None:
        try:
            self._write(rgb)
        except Exception:
            now = self._clock()
            if now - self._last_write_error >= 1.0:
                logger.warning("ring write failed", exc_info=True)
                self._last_write_error = now
            return
        self._last = rgb
