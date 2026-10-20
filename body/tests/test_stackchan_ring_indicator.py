"""The StackChan ring indicator: the Indicator the 12-pixel ring answers.

Covers docs/dev/led-standard-2026-10-20.md: one colour per whole-ring
write, styles driven by the host timer through ``tick()``, the pulse
flash, and the contract that a failing ``write`` is logged, never raised.
"""

from __future__ import annotations

import logging

import pytest

from maipai_body.bodies.stackchan.profile import LED_CHANNEL_MAX
from maipai_body.bodies.stackchan.ring import ring_rgb
from maipai_body.bodies.stackchan.ring_indicator import StackChanRingIndicator
from maipai_body.hal.seam import Indicator, Look, LookStyle, Palette
from maipai_body.indicator.looks import LOOKS, period_s


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Recorder:
    def __init__(self) -> None:
        self.writes: list[tuple[int, int, int]] = []

    def __call__(self, rgb: tuple[int, int, int]) -> None:
        self.writes.append(rgb)


def make(clock: FakeClock | None = None) -> tuple[StackChanRingIndicator, Recorder, FakeClock]:
    clock = clock if clock is not None else FakeClock()
    recorder = Recorder()
    return StackChanRingIndicator(recorder, clock=clock), recorder, clock


_STEADY = Look(colour=Palette.WHITE, brightness=1.0, style=LookStyle.STEADY, period_s=0.0)


def test_spec_declares_the_palette_without_off_and_is_connected():
    indicator, _, _ = make()
    spec = indicator.spec()
    assert spec.connected is True
    assert Palette.OFF not in spec.palette
    assert spec.palette == [colour for colour in Palette if colour is not Palette.OFF]
    assert all("red" not in colour.value for colour in spec.palette)
    assert spec.pulses == ["blink", "ack"]
    assert isinstance(indicator, Indicator)


def test_steady_look_writes_once_and_ticks_write_nothing():
    indicator, recorder, clock = make()
    indicator.set_look(_STEADY)
    assert recorder.writes == [ring_rgb(_STEADY, 0.0, 0.0)]
    for _ in range(5):
        clock.advance(0.05)
        indicator.tick()
    assert len(recorder.writes) == 1


def test_setting_the_same_look_twice_does_not_restart_the_style_clock():
    indicator, recorder, clock = make()
    look = Look(colour=Palette.WHITE, brightness=1.0, style=LookStyle.BREATHE, period_s=2.0)
    indicator.set_look(look)
    clock.advance(1.0)
    indicator.set_look(look)
    assert len(recorder.writes) == 1
    clock.advance(1.0)
    indicator.tick()
    assert recorder.writes[-1] == ring_rgb(look, 2.0, 2.0)


def test_breathe_look_writes_changing_colours_within_channel_max():
    indicator, recorder, clock = make()
    look = Look(colour=Palette.WHITE, brightness=1.0, style=LookStyle.BREATHE, period_s=2.0)
    indicator.set_look(look)
    for i in range(1, 17):
        clock.advance(0.125)
        indicator.tick()
        assert recorder.writes[-1] == ring_rgb(look, 2.0, 0.125 * i)
    assert len(set(recorder.writes)) > 1
    for rgb in recorder.writes:
        for channel in rgb:
            assert 0 <= channel <= LED_CHANNEL_MAX


def test_pulse_look_is_on_for_a_quarter_then_off():
    indicator, recorder, clock = make()
    look = Look(colour=Palette.WHITE, brightness=1.0, style=LookStyle.PULSE, period_s=2.0)
    on = ring_rgb(look, 2.0, 0.1)
    assert on != (0, 0, 0)
    indicator.set_look(look)
    clock.advance(0.1)
    indicator.tick()
    assert recorder.writes[-1] == on
    clock.advance(0.2)
    indicator.tick()
    assert recorder.writes[-1] == (0, 0, 0)
    clock.advance(1.7)
    indicator.tick()
    assert recorder.writes[-1] == on


def test_flash_look_matches_the_style_factor_timeline():
    indicator, recorder, clock = make()
    look = Look(colour=Palette.PINK, brightness=1.0, style=LookStyle.FLASH, period_s=0.5)
    on = ring_rgb(look, 0.5, 0.05)
    assert on != (0, 0, 0)
    indicator.set_look(look)
    previous = 0.0
    for t in (0.05, 0.15, 0.25, 0.35, 0.45, 0.55):
        clock.advance(t - previous)
        previous = t
        indicator.tick()
        assert recorder.writes[-1] == ring_rgb(look, 0.5, t)
    assert recorder.writes == [on, (0, 0, 0), on, (0, 0, 0), on]


def test_pulse_flashes_then_the_look_returns_after_point_fifteen_s():
    indicator, recorder, clock = make()
    indicator.set_look(_STEADY)
    base = recorder.writes[0]
    flash = ring_rgb(Look(colour=Palette.WHITE, brightness=0.5), 0.0, 0.0)
    assert flash != base
    indicator.pulse("ack")
    assert recorder.writes[-1] == flash
    clock.advance(0.1)
    indicator.tick()
    assert recorder.writes[-1] == flash
    clock.advance(0.06)
    indicator.tick()
    assert recorder.writes[-1] == base
    clock.advance(1.0)
    indicator.tick()
    assert recorder.writes[-1] == base
    assert len(recorder.writes) == 3


def test_pulse_rejects_any_name_outside_blink_and_ack():
    indicator, recorder, _ = make()
    with pytest.raises(ValueError, match="unknown pulse"):
        indicator.pulse("startle")
    assert recorder.writes == []


def test_off_writes_zeros_and_stays_dark():
    indicator, recorder, clock = make()
    indicator.set_look(_STEADY)
    indicator.off()
    assert recorder.writes[-1] == (0, 0, 0)
    clock.advance(0.5)
    indicator.tick()
    assert len(recorder.writes) == 2


def test_a_raising_write_never_propagates_and_logs_at_most_once_a_second(caplog):
    clock = FakeClock()

    def boom(rgb: tuple[int, int, int]) -> None:
        raise RuntimeError("the ring is gone")

    indicator = StackChanRingIndicator(boom, clock=clock)
    look = Look(colour=Palette.WHITE, brightness=1.0, style=LookStyle.BREATHE, period_s=2.0)
    with caplog.at_level("WARNING", logger="maipai_body.bodies.stackchan.ring_indicator"):
        indicator.set_look(look)
        clock.advance(0.5)
        indicator.tick()
        clock.advance(0.5)
        indicator.tick()
        indicator.pulse("blink")
        clock.advance(2.0)
        indicator.tick()
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 3


def test_every_look_key_sets_a_triple_within_channel_max():
    indicator, recorder, _ = make()
    for key in LOOKS:
        colour, weight, style = LOOKS[key]
        look = Look(colour=colour, brightness=weight, style=style, period_s=period_s(key))
        recorder.writes.clear()
        indicator.set_look(look)
        assert len(recorder.writes) == 1
        for channel in recorder.writes[0]:
            assert 0 <= channel <= LED_CHANNEL_MAX
