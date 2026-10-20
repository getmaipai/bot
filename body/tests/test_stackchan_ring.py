"""The StackChan ring renderer: translate a Look into a 12-pixel RGB triple.

Covers docs/dev/led-standard-2026-10-20.md: the one colour map, the five
styles, the camera flash sequence and a sweep over the whole look table.
"""

from __future__ import annotations

from maipai_body.bodies.stackchan.profile import LED_CHANNEL_MAX
from maipai_body.bodies.stackchan.ring import (
    RING_RGB,
    camera_flash_frames,
    ring_rgb,
    style_factor,
)
from maipai_body.hal.seam import Look, LookStyle, Palette
from maipai_body.indicator.looks import LOOKS, LookKey, period_s

_T_VALUES = (0.05, 0.25, 0.5, 1.0, 1.75, 3.0, 5.0, 7.3)
_STYLES = list(LookStyle)
_PERIODS = (0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 10.0, 20.0)


def test_steady_is_channel_max_times_fraction_times_brightness():
    look = Look(colour=Palette.WHITE, brightness=0.5, style=LookStyle.STEADY)
    assert ring_rgb(look, period_s(LookKey.IDLE), 1.0) == (84, 84, 76)
    assert ring_rgb(look, 0.0, 3.5) == (84, 84, 76)


def test_no_output_channel_exceeds_channel_max():
    for colour in Palette:
        for style in _STYLES:
            for period in _PERIODS:
                for t in _T_VALUES:
                    look = Look(colour=colour, brightness=1.0, style=style)
                    for channel in ring_rgb(look, period, t):
                        assert 0 <= channel <= LED_CHANNEL_MAX


def test_pink_at_full_brightness_rounds_to_168_42_92():
    look = Look(colour=Palette.PINK, brightness=1.0, style=LookStyle.STEADY)
    assert ring_rgb(look, 0.0, 0.0) == (168, 42, 92)


def test_no_palette_member_is_pure_red():
    assert RING_RGB[Palette.OFF] == (0.0, 0.0, 0.0)
    for colour in Palette:
        for style in _STYLES:
            for period in _PERIODS:
                for t in _T_VALUES:
                    red, green, blue = ring_rgb(
                        Look(colour=colour, brightness=1.0, style=style), period, t
                    )
                    assert not (red > 0 and green == 0 and blue == 0), colour


def test_breathe_starts_dim_and_peaks_mid_period():
    assert style_factor(LookStyle.BREATHE, 4.0, 0.0) == 0.15
    assert style_factor(LookStyle.BREATHE, 4.0, 2.0) == 1.0
    assert 0.0 < style_factor(LookStyle.BREATHE, 4.0, 1.0) < 1.0


def test_pulse_is_on_for_a_quarter_then_off():
    assert style_factor(LookStyle.PULSE, 2.0, 0.0) == 1.0
    assert style_factor(LookStyle.PULSE, 2.0, 0.1) == 1.0
    assert style_factor(LookStyle.PULSE, 2.0, 0.3) == 0.0
    assert style_factor(LookStyle.PULSE, 2.0, 2.1) == 1.0
    assert style_factor(LookStyle.PULSE, 2.0, 2.3) == 0.0


def test_flash_timeline_on_off_on_off_then_steady():
    factors = [style_factor(LookStyle.FLASH, 0.5, t) for t in (0.05, 0.15, 0.25, 0.35, 0.45)]
    assert factors == [1.0, 0.0, 1.0, 0.0, 1.0]


def test_zero_period_guards_as_steady():
    for style in _STYLES:
        assert style_factor(style, 0.0, 1.0) == 1.0


def test_off_and_none_are_dark():
    assert ring_rgb(None, 2.0, 1.0) == (0, 0, 0)
    off = Look(colour=Palette.OFF, brightness=1.0, style=LookStyle.STEADY)
    assert ring_rgb(off, 0.0, 0.0) == (0, 0, 0)


def test_camera_flash_frames_are_on_off_on():
    look = Look(colour=Palette.PINK, brightness=1.0, style=LookStyle.FLASH)
    assert camera_flash_frames(look) == [
        ((168, 42, 92), 0.1),
        ((0, 0, 0), 0.1),
        ((168, 42, 92), 0.1),
    ]


def test_every_look_key_renders_to_a_triple():
    for key, (colour, weight, style) in LOOKS.items():
        look = Look(colour=colour, brightness=weight, style=style)
        triple = ring_rgb(look, period_s(key), 1.0)
        assert len(triple) == 3
        for channel in triple:
            assert 0 <= channel <= LED_CHANNEL_MAX
    for key in (LookKey.LIVE, LookKey.CAMERA):
        colour, _, style = LOOKS[key]
        look = Look(colour=colour, brightness=0.5, style=style)
        assert sum(ring_rgb(look, period_s(key), 1.0)) > 0
