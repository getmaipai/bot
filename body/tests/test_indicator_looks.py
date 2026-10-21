"""EYES-02: the one look table (indicator/looks.py) and its rules."""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from maipai_body.hal.seam import LookStyle, Palette
from maipai_body.indicator import looks
from maipai_body.indicator.looks import LookKey, LookRequest, resolve
from maipai_body.indicator.settings import IndicatorSettings
from maipai_body.presence.carry_reaction import PresenceEntry
from maipai_body.presence.funnel import FunnelState

PACKAGE = Path(__file__).resolve().parent.parent / "maipai_body"
ADULT = PresenceEntry("adult")
CHILD = PresenceEntry("child")
TEEN = PresenceEntry("teen")
UNKNOWN = PresenceEntry("unknown")
NIGHT_MINUTE = 23 * 60
DAY_MINUTE = 12 * 60


def _request(**kwargs) -> LookRequest:
    base = {
        "funnel": FunnelState.IDLE,
        "minute": DAY_MINUTE,
        "settings": IndicatorSettings(),
        "presence": [ADULT],
    }
    base.update(kwargs)
    return LookRequest(**base)


def test_floors_and_period_are_the_ordered_constants():
    assert looks.LIVE_FLOOR == 0.5
    assert looks.CAMERA_FLOOR == 0.5
    assert looks.ALARM_PERIOD_S >= 1.0


def test_the_table_has_a_row_for_every_state_and_no_red():
    assert {key.value for key in LookKey} >= {
        "live",
        "camera",
        "alarm",
        "held",
        "muted",
        "idle",
        "listening",
        "thinking",
        "speaking",
        "sleep",
    }
    for colour, weight, style in looks.LOOKS.values():
        assert colour in set(Palette)
        assert 0.0 <= weight <= 1.0
        assert style in set(LookStyle)
    assert "red" not in {colour.value for colour, _, _ in looks.LOOKS.values()}


@pytest.mark.parametrize("level", [0.0, 0.2, 1.0])
@pytest.mark.parametrize("presence", [[ADULT], [CHILD], None])
@pytest.mark.parametrize("minute", [DAY_MINUTE, NIGHT_MINUTE])
def test_live_and_camera_never_fall_below_their_floors(level, presence, minute):
    settings = IndicatorSettings(brightness=max(level, 0.2), night_brightness=0.0)
    live = resolve(_request(live=True, settings=settings, presence=presence, minute=minute))
    camera = resolve(_request(camera=True, settings=settings, presence=presence, minute=minute))
    assert live.colour is Palette.GREEN and live.brightness >= looks.LIVE_FLOOR
    assert camera.colour is Palette.PINK
    assert camera.style is LookStyle.FLASH
    assert camera.brightness >= looks.CAMERA_FLOOR


def test_live_outranks_camera_alarm_held_muted_and_the_funnel():
    request = _request(
        live=True,
        camera=True,
        alarm=True,
        alarm_on=True,
        held=True,
        muted=True,
        funnel=FunnelState.SPEAKING,
    )
    assert resolve(request).colour is Palette.GREEN
    assert resolve(_request(camera=True, alarm=True, alarm_on=True)).colour is Palette.PINK
    assert resolve(_request(alarm=True, alarm_on=True, held=True)).colour is Palette.AMBER


def test_alarm_needs_its_setting_and_blinks_between_two_levels():
    off_setting = IndicatorSettings(alarm=False)
    quiet = resolve(_request(alarm=True, alarm_on=True, settings=off_setting))
    assert quiet is None or quiet.colour is not Palette.AMBER
    on = resolve(_request(alarm=True, alarm_on=True))
    dim = resolve(_request(alarm=True, alarm_on=False))
    assert on.colour is dim.colour is Palette.AMBER
    assert on.brightness > dim.brightness


@pytest.mark.parametrize(
    ("state", "key"),
    [
        (FunnelState.LISTENING, LookKey.LISTENING),
        (FunnelState.THINKING, LookKey.THINKING),
        (FunnelState.SPEAKING, LookKey.SPEAKING),
    ],
)
def test_each_funnel_state_shows_its_table_row(state, key):
    look = resolve(_request(funnel=state))
    assert look.colour is looks.LOOKS[key][0]


def test_idle_awake_is_dark():
    assert resolve(_request(funnel=FunnelState.IDLE)) is None


def test_held_and_muted_rows_outrank_the_funnel_state():
    assert (
        resolve(_request(held=True, funnel=FunnelState.SPEAKING)).colour
        is (looks.LOOKS[LookKey.HELD][0])
    )
    assert (
        resolve(_request(muted=True, funnel=FunnelState.SPEAKING)).colour
        is (looks.LOOKS[LookKey.MUTED][0])
    )


def test_a_disabled_indicator_shows_nothing_but_the_capture_cues():
    off = IndicatorSettings(enabled=False)
    assert resolve(_request(settings=off, funnel=FunnelState.SPEAKING, held=True)) is None
    assert resolve(_request(settings=off, live=True)).colour is Palette.GREEN
    assert resolve(_request(settings=off, camera=True)).colour is Palette.PINK


def test_night_uses_the_night_level_and_a_child_lowers_it_further():
    settings = IndicatorSettings(brightness=0.8, night_brightness=0.3)
    day = resolve(_request(funnel=FunnelState.LISTENING, settings=settings))
    night_adult = resolve(
        _request(funnel=FunnelState.LISTENING, settings=settings, minute=NIGHT_MINUTE)
    )
    night_child = resolve(
        _request(
            funnel=FunnelState.LISTENING,
            settings=settings,
            minute=NIGHT_MINUTE,
            presence=[ADULT, CHILD],
        )
    )
    assert day.brightness > night_adult.brightness > night_child.brightness > 0.0


@pytest.mark.parametrize("presence", [[CHILD], [TEEN], [UNKNOWN], None])
def test_a_child_teen_unknown_or_missing_presence_gets_the_lowest_night_level(presence):
    adult = resolve(_request(funnel=FunnelState.THINKING, minute=NIGHT_MINUTE))
    other = resolve(_request(funnel=FunnelState.THINKING, minute=NIGHT_MINUTE, presence=presence))
    assert other.brightness < adult.brightness


def test_nobody_present_is_not_unknown():
    adult = resolve(_request(funnel=FunnelState.THINKING, minute=NIGHT_MINUTE, presence=[ADULT]))
    empty = resolve(_request(funnel=FunnelState.THINKING, minute=NIGHT_MINUTE, presence=[]))
    assert empty.brightness == adult.brightness


def test_sleep_eyes_governs_the_idle_night_look():
    dim = resolve(_request(minute=NIGHT_MINUTE, settings=IndicatorSettings(sleep_eyes="dim")))
    dark = resolve(_request(minute=NIGHT_MINUTE, settings=IndicatorSettings(sleep_eyes="off")))
    assert dim is not None and dim.colour is looks.LOOKS[LookKey.SLEEP][0]
    assert dark is None


def test_night_window_wraps_midnight():
    assert looks.is_night(23 * 60, 21 * 60, 7 * 60)
    assert looks.is_night(3 * 60, 21 * 60, 7 * 60)
    assert not looks.is_night(12 * 60, 21 * 60, 7 * 60)
    assert looks.is_night(2 * 60, 1 * 60, 5 * 60)
    assert not looks.is_night(6 * 60, 1 * 60, 5 * 60)


def _literal_hits(path: Path) -> list[str]:
    text = path.read_text()
    hits = []
    for pattern in (r"Palette\.[A-Z]+", r"\bLook\(", r"brightness\s*=\s*[0-9]"):
        hits += re.findall(pattern, text)
    return hits


def test_looks_py_is_the_only_colour_or_level_literal_site_in_indicator():
    for path in sorted((PACKAGE / "indicator").glob("*.py")):
        if path.name == "looks.py":
            continue
        assert _literal_hits(path) == [], path.name


def test_no_module_outside_the_seam_and_the_client_names_a_palette_member():
    allowed = {
        PACKAGE / "hal" / "seam.py",
        PACKAGE / "bodies" / "reachy_mini" / "eyes_client.py",
        PACKAGE / "bodies" / "reachy_mini" / "fake.py",
        # One palette-to-hardware map per body (the light standard); no colour name elsewhere.
        PACKAGE / "bodies" / "stackchan" / "ring.py",
        PACKAGE / "bodies" / "stackchan" / "ring_indicator.py",
        PACKAGE / "indicator" / "looks.py",
    }
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if path not in allowed and re.search(r"Palette\.[A-Z]+", path.read_text())
    ]
    assert offenders == []


def test_the_offer_look_shows_over_idle_and_below_held_and_muted():
    offer = resolve(_request(offer=True))
    assert offer is not None and offer.colour is Palette.BLUE
    assert offer != resolve(_request(funnel=FunnelState.LISTENING))
    assert resolve(_request(offer=True, muted=True)) == resolve(_request(muted=True))
    assert resolve(_request(offer=True, held=True)) == resolve(_request(held=True))
    # A turn in progress shows its own state, not the offer.
    assert resolve(_request(offer=True, funnel=FunnelState.THINKING)) == resolve(
        _request(funnel=FunnelState.THINKING)
    )


def test_the_error_look_is_amber_steady_and_outranks_held_and_muted_but_not_the_cues():
    error = resolve(_request(fault=True, held=True, muted=True))
    assert error is not None and error.colour is Palette.AMBER
    assert error != resolve(_request(muted=True))
    assert resolve(_request(fault=True, live=True)) == resolve(_request(live=True))
    assert resolve(_request(fault=True, settings=IndicatorSettings(enabled=False))) is None


@pytest.mark.parametrize(
    ("kwargs", "key"),
    [
        ({"connecting": True}, LookKey.CONNECTING),
        ({"offline": True}, LookKey.OFFLINE),
        ({"pairing": True}, LookKey.PAIRING),
        ({"charging": True}, LookKey.CHARGING),
        ({"battery_low": True}, LookKey.BATTERY_LOW),
        ({"updating": True}, LookKey.UPDATING),
        ({"dancing": True}, LookKey.DANCING),
    ],
)
def test_each_new_row_shows_its_table_entry(kwargs, key):
    colour, weight, style = looks.LOOKS[key]
    settings = IndicatorSettings(brightness=0.8)
    look = resolve(_request(**kwargs, settings=settings))
    assert look is not None
    assert look.colour is colour
    assert look.style is style
    assert look.brightness == pytest.approx(weight * 0.8)


def test_each_new_row_is_dark_when_the_level_is_zero():
    off = IndicatorSettings(brightness=0.0, night_brightness=0.0)
    for kwargs in (
        {"connecting": True},
        {"offline": True},
        {"pairing": True},
        {"charging": True},
        {"battery_low": True},
        {"updating": True},
        {"dancing": True},
    ):
        assert resolve(_request(**kwargs, settings=off)) is None


@pytest.mark.parametrize(
    ("higher", "lower"),
    [
        ({"updating": True}, {"pairing": True}),
        ({"pairing": True}, {"connecting": True}),
        ({"connecting": True}, {"offline": True}),
        ({"offline": True}, {"battery_low": True}),
        ({"battery_low": True}, {"offer": True}),
        ({"offer": True}, {"charging": True}),
        ({"charging": True}, {"dancing": True}),
        ({"fault": True}, {"updating": True}),
        ({"held": True}, {"pairing": True}),
        ({"muted": True}, {"connecting": True}),
    ],
)
def test_the_new_rows_keep_their_priority_order(higher, lower):
    merged = {**higher, **lower}
    assert resolve(_request(**merged)).colour == resolve(_request(**higher)).colour


def test_the_new_rows_outrank_the_funnel_but_the_idle_only_ones_do_not():
    for kwargs in (
        {"updating": True},
        {"pairing": True},
        {"connecting": True},
        {"offline": True},
        {"battery_low": True},
    ):
        assert resolve(_request(**kwargs, funnel=FunnelState.SPEAKING)) == resolve(
            _request(**kwargs)
        )
    assert resolve(_request(charging=True, funnel=FunnelState.SPEAKING)) == resolve(
        _request(funnel=FunnelState.SPEAKING)
    )
    assert resolve(_request(dancing=True, funnel=FunnelState.SPEAKING)) == resolve(
        _request(funnel=FunnelState.SPEAKING)
    )
    # The cues and the alarm stay above every new row.
    for kwargs in ({"live": True}, {"camera": True}, {"alarm": True, "alarm_on": True}):
        assert resolve(_request(**kwargs, updating=True, pairing=True, dancing=True)) == resolve(
            _request(**kwargs)
        )


def test_resolve_key_agrees_with_resolve_over_a_seeded_sweep():
    flags = [
        "live",
        "camera",
        "alarm",
        "fault",
        "held",
        "muted",
        "updating",
        "pairing",
        "connecting",
        "offline",
        "battery_low",
        "offer",
        "charging",
        "dancing",
    ]
    rng = random.Random(20)
    for _ in range(3000):
        kwargs = {flag: rng.random() < 0.5 for flag in flags}
        kwargs["alarm_on"] = rng.random() < 0.5
        kwargs["funnel"] = rng.choice(list(FunnelState))
        kwargs["minute"] = rng.choice([DAY_MINUTE, NIGHT_MINUTE])
        request = _request(**kwargs)
        key = looks.resolve_key(request)
        look = resolve(request)
        if key is None:
            assert look is None
        else:
            assert look is not None
            assert look.colour is looks.LOOKS[key][0]
            assert look.style is looks.LOOKS[key][2]


def test_the_periods_are_the_unmeasured_defaults():
    assert looks.PERIOD_S[LookStyle.BREATHE] == 3.0
    assert looks.PERIOD_S[LookStyle.PULSE] == 2.0
    assert looks.PERIOD_S[LookStyle.FLASH] == 0.5
    assert looks.PERIOD_S[LookStyle.BLINK] == 1.0
    assert looks.PERIOD_S[LookStyle.STEADY] == 0.0


def test_period_s_uses_the_override_then_the_style():
    assert looks.period_s(LookKey.CHARGING) == 4.0
    assert looks.period_s(LookKey.CONNECTING) == 2.0
    assert looks.period_s(LookKey.UPDATING) == 1.0
    assert looks.period_s(LookKey.PAIRING) == 2.0
    assert looks.period_s(LookKey.OFFLINE) == 10.0
    assert looks.period_s(LookKey.BATTERY_LOW) == 20.0
    assert looks.period_s(LookKey.THINKING) == 3.0
    assert looks.period_s(LookKey.CAMERA) == 0.5
    assert looks.period_s(LookKey.DANCING) == 0.0


def test_camera_is_pink_flash_at_its_floor_even_night_with_a_child():
    settings = IndicatorSettings(brightness=0.2, night_brightness=0.0)
    look = resolve(_request(camera=True, settings=settings, minute=NIGHT_MINUTE, presence=[CHILD]))
    assert look is not None
    assert look.colour is Palette.PINK
    assert look.style is LookStyle.FLASH
    assert look.brightness >= looks.CAMERA_FLOOR


def test_disabled_darkens_every_new_row_but_never_the_cues_or_the_alarm():
    off = IndicatorSettings(enabled=False)
    for kwargs in (
        {"connecting": True},
        {"offline": True},
        {"pairing": True},
        {"charging": True},
        {"battery_low": True},
        {"updating": True},
        {"dancing": True},
        {"fault": True},
        {"held": True},
        {"muted": True},
    ):
        assert resolve(_request(**kwargs, settings=off)) is None
    assert resolve(_request(live=True, settings=off)) is not None
    assert resolve(_request(camera=True, settings=off)) is not None
    assert resolve(_request(alarm=True, alarm_on=True, settings=off)) is not None


def test_offline_is_an_amber_double_pulse_every_ten_seconds():
    look = resolve(_request(offline=True))
    assert look is not None and look.colour is Palette.AMBER
    assert look.style.value == "double" and look.period_s == 10.0
