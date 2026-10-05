"""The indicator seam: what the eyes may show, and what they may never do.

Bot-internal name is ``indicator``; the spec capability id is the existing
``eyes``. Nothing here reads a vendor's code or imports a vendor module.
"""

from __future__ import annotations

import typing

import pytest
from pydantic import ValidationError

from maipai_body.bodies.reachy_mini.fake import FakeEyes
from maipai_body.hal import seam
from maipai_body.hal.errors import BodyLost
from maipai_body.hal.seam import Indicator, IndicatorSpec, Look, NullIndicator, Palette

_PALETTE = {"WHITE", "GREEN", "BLUE", "AMBER", "CYAN", "MAGENTA", "OFF"}


def test_the_palette_is_exactly_the_approved_set():
    assert {member.name for member in Palette} == _PALETTE


def test_no_red_is_representable():
    # By name, by value, by a hue string and by any case.
    for spelling in ("RED", "red", "Red", "#ff0000", "ff0000", "crimson"):
        assert spelling not in {m.name for m in Palette}
        assert spelling.lower() not in {str(m.value).lower() for m in Palette}
        with pytest.raises(ValueError):
            Palette(spelling)
        with pytest.raises(ValidationError):
            Look(colour=spelling)  # type: ignore[arg-type]
    assert not hasattr(Palette, "RED")


def test_no_palette_value_is_a_red_hue():
    # Every colour a body may be told to show is a named member; none maps to a
    # raw RGB triple, so a red cannot ride in under another name.
    for member in Palette:
        assert isinstance(member.value, str)
        assert "red" not in member.value.lower()


def test_a_look_accepts_a_palette_member_and_a_brightness_in_range():
    look = Look(colour=Palette.GREEN, brightness=0.5)
    assert look.colour is Palette.GREEN
    assert look.brightness == 0.5
    for bad in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            Look(colour=Palette.GREEN, brightness=bad)


def test_only_blink_and_ack_pulse():
    eyes = FakeEyes()
    eyes.pulse("blink")
    eyes.pulse("ack")
    assert [c.pulse for c in eyes.commands] == ["blink", "ack"]
    for refused in ("startle", "flash", "strobe", "", "BLINK"):
        with pytest.raises(ValueError):
            eyes.pulse(refused)  # type: ignore[arg-type]
    assert len(eyes.commands) == 2


def test_the_seam_has_no_startle():
    names = [name for name in dir(seam) if "startle" in name.lower()]
    assert names == []
    assert not hasattr(Indicator, "startle")
    assert not hasattr(FakeEyes, "startle")
    assert not hasattr(NullIndicator, "startle")
    pulses = typing.get_args(seam.PulseName)
    assert set(pulses) == {"blink", "ack"}


def test_the_spec_names_the_palette_and_the_pulses_the_seam_allows():
    spec = FakeEyes().spec()
    assert isinstance(spec, IndicatorSpec)
    assert spec.connected is True
    assert {c.name for c in spec.palette} == _PALETTE
    assert set(spec.pulses) == {"blink", "ack"}


def test_fake_eyes_records_each_call_in_order_with_the_clock_reading():
    now = [10.0]
    eyes = FakeEyes(clock=lambda: now[0])
    eyes.set_look(Look(colour=Palette.BLUE, brightness=0.25))
    now[0] = 10.5
    eyes.pulse("ack")
    now[0] = 11.0
    eyes.off()
    assert [(c.kind, c.t_s) for c in eyes.commands] == [
        ("set_look", 10.0),
        ("pulse", 10.5),
        ("off", 11.0),
    ]
    assert eyes.commands[0].look == Look(colour=Palette.BLUE, brightness=0.25)
    assert eyes.current_look is None  # off() clears what was showing


def test_fake_eyes_current_look_is_the_last_one_set():
    eyes = FakeEyes()
    assert eyes.current_look is None
    eyes.set_look(Look(colour=Palette.AMBER))
    eyes.set_look(Look(colour=Palette.CYAN))
    assert eyes.current_look == Look(colour=Palette.CYAN)


def test_fakes_satisfy_the_indicator_protocol():
    assert isinstance(FakeEyes(), Indicator)
    assert isinstance(NullIndicator(), Indicator)


def test_absent_device_never_raises():
    for eyes in (NullIndicator(), FakeEyes(connected=False)):
        assert eyes.spec().connected is False
        eyes.set_look(Look(colour=Palette.GREEN))
        eyes.pulse("blink")
        eyes.pulse("ack")
        eyes.off()


def test_absent_device_never_raises_body_lost():
    eyes = FakeEyes(connected=False)
    try:
        eyes.set_look(Look(colour=Palette.WHITE))
        eyes.pulse("ack")
        eyes.off()
    except BodyLost:  # pragma: no cover - the failure this test names
        pytest.fail("an absent eyes device raised BodyLost")


def test_absent_device_returns_at_once_and_records_nothing():
    eyes = FakeEyes(connected=False)
    eyes.set_look(Look(colour=Palette.GREEN))
    eyes.pulse("blink")
    eyes.off()
    assert eyes.commands == []
    assert eyes.current_look is None


def test_unplugging_mid_session_degrades_to_absent_without_raising():
    eyes = FakeEyes()
    eyes.set_look(Look(colour=Palette.GREEN))
    eyes.unplug()
    assert eyes.spec().connected is False
    eyes.set_look(Look(colour=Palette.BLUE))
    eyes.pulse("ack")
    assert [c.kind for c in eyes.commands] == ["set_look"]


def test_a_bad_pulse_name_on_an_absent_device_still_refuses():
    # Refusing a name is a caller bug, not a device loss, and does not depend
    # on whether a device is plugged in.
    for eyes in (NullIndicator(), FakeEyes(connected=False)):
        with pytest.raises(ValueError):
            eyes.pulse("startle")  # type: ignore[arg-type]
