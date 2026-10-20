"""The StackChan ring renderer (docs/dev/led-standard-2026-10-20.md).

Translates one look from the look table into a 12-pixel RGB triple for the
ring. This module is the one place StackChan names a colour as numbers; the
periods it is driven at are UNMEASURED design defaults.
"""

from __future__ import annotations

import math

from maipai_body.bodies.stackchan.profile import LED_CHANNEL_MAX
from maipai_body.hal.seam import Look, LookStyle, Palette

# Full-scale channel fractions 0..1 per palette member. No red: a red ring on
# a face that watches a child reads as alarm, so no entry may have red as its
# only nonzero channel (checked once below).
RING_RGB: dict[Palette, tuple[float, float, float]] = {
    Palette.WHITE: (1.0, 1.0, 0.9),
    Palette.GREEN: (0.0, 1.0, 0.1),
    Palette.BLUE: (0.0, 0.2, 1.0),
    Palette.AMBER: (1.0, 0.45, 0.0),
    Palette.CYAN: (0.0, 0.9, 1.0),
    Palette.MAGENTA: (0.75, 0.0, 1.0),
    Palette.PINK: (1.0, 0.25, 0.55),
    Palette.OFF: (0.0, 0.0, 0.0),
}


def _check_no_pure_red() -> None:
    for colour, (red, green, blue) in RING_RGB.items():
        assert not (red > 0.0 and green == 0.0 and blue == 0.0), f"{colour} is pure red"


_check_no_pure_red()


def style_factor(style: LookStyle, period_s: float, t_s: float) -> float:
    """The 0..1 brightness multiplier for ``style`` at ``t_s`` seconds in.

    ``t_s`` counts from when the look began. A non-positive period guards as
    steady.
    """
    if period_s <= 0.0 or style is LookStyle.STEADY:
        return 1.0
    if style is LookStyle.BREATHE:
        return 0.15 + 0.85 * (0.5 - 0.5 * math.cos(2.0 * math.pi * t_s / period_s))
    if style is LookStyle.PULSE:
        return 1.0 if t_s % period_s < 0.25 else 0.0
    if style is LookStyle.BLINK:
        return 1.0 if t_s % period_s < period_s / 2.0 else 0.15
    if style is LookStyle.FLASH:
        if t_s < 0.1:
            return 1.0
        if t_s < 0.2:
            return 0.0
        if t_s < 0.3:
            return 1.0
        if t_s < 0.4:
            return 0.0
        return 1.0
    raise ValueError(f"unknown style {style!r}")


def _clamp(value: float) -> int:
    return max(0, min(LED_CHANNEL_MAX, round(value)))


def ring_rgb(look: Look | None, period_s: float, t_s: float) -> tuple[int, int, int]:
    """The (red, green, blue) channels to send for ``look`` at ``t_s`` seconds.

    ``None`` or an OFF look is dark; otherwise each channel is the palette
    fraction times the look's brightness times the style factor, scaled to
    ``LED_CHANNEL_MAX`` and clamped.
    """
    if look is None or look.colour is Palette.OFF:
        return (0, 0, 0)
    red, green, blue = RING_RGB[look.colour]
    factor = style_factor(look.style, period_s, t_s)
    return tuple(
        _clamp(LED_CHANNEL_MAX * channel * look.brightness * factor)
        for channel in (
            red,
            green,
            blue,
        )
    )


def camera_flash_frames(look: Look) -> list[tuple[tuple[int, int, int], float]]:
    """The camera cue's start sequence as (rgb, seconds) frames.

    On 0.1 s, off 0.1 s, on 0.1 s; the steady colour that follows is held by
    the caller. Uses the look's colour and brightness (its floor already
    applied by the caller).
    """
    red, green, blue = RING_RGB[look.colour]
    on = (
        _clamp(LED_CHANNEL_MAX * red * look.brightness),
        _clamp(LED_CHANNEL_MAX * green * look.brightness),
        _clamp(LED_CHANNEL_MAX * blue * look.brightness),
    )
    return [(on, 0.1), ((0, 0, 0), 0.1), (on, 0.1)]
