"""EYES-02: the one look table, the standard it must equal, and its rules."""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from maipai_body.hal.seam import LookStyle, Palette
from maipai_body.indicator import looks
from maipai_body.indicator.looks import LookKey, LookRequest, resolve, resolve_key
from maipai_body.indicator.settings import IndicatorSettings
from maipai_body.presence.carry_reaction import PresenceEntry
from maipai_body.presence.funnel import FunnelState

PACKAGE = Path(__file__).resolve().parent.parent / "maipai_body"
ADULT = PresenceEntry("adult")
CHILD = PresenceEntry("child")
TEEN = PresenceEntry("teen")
UNKNOWN = PresenceEntry("unknown")
STANDARD = Path(__file__).resolve().parents[2] / "docs" / "dev" / "led-standard-2026-10-20.md"
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


def test_floors_are_the_ordered_constants():
    assert looks.LIVE_FLOOR == 0.5
    assert looks.CAMERA_FLOOR == 0.5


def _standard_rows() -> dict[str, list[str]]:
    """The ring table of the standard doc: key -> its cells. The doc is the single source."""
    text = STANDARD.read_text()
    assert "approved by the owner 2026-11-13" in text
    section = text.split("## The ring table", 1)[1].split("\n## ", 1)[0]
    rows: dict[str, list[str]] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        match = re.fullmatch(r"`([a-z_]+)`", cells[0]) if cells and line.startswith("|") else None
        if match:
            rows[match.group(1)] = cells
    return rows


def _number(cell: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", cell)
    return float(match.group(0)) if match else None


def test_no_look_key_exists_outside_the_standards_table():
    rows = _standard_rows()
    assert {key.value for key in LookKey} == set(rows), "looks.py and the standard doc differ"
    assert list(rows) == [key.value for key in LookKey], "the doc lists the rows in priority order"


def test_every_row_equals_the_standards_table():
    for name, cells in _standard_rows().items():
        key = LookKey(name)
        colour, weight, style = looks.LOOKS[key]
        _, _, doc_colour, doc_style, doc_period, doc_brightness, _ = cells[:7]
        if key is LookKey.IDLE:
            assert weight == 0.0
            continue
        assert colour.value == doc_colour, name
        assert style.value == doc_style, name
        assert looks.period_s(key) == (_number(doc_period) or 0.0), name
        if key in looks.FIXED_ROWS:
            assert weight == _number(doc_brightness), name
        if key is LookKey.LIVE:
            assert looks.LIVE_FLOOR == _number(doc_brightness)
        if key is LookKey.CAMERA:
            assert looks.CAMERA_FLOOR == _number(doc_brightness)


def test_the_table_has_no_red_and_one_meaning_per_colour():
    for colour, weight, style in looks.LOOKS.values():
        assert colour in set(Palette)
        assert 0.0 <= weight <= 1.0
        assert style in set(LookStyle)
    assert "red" not in {colour.value for colour, _, _ in looks.LOOKS.values()}
    lit = {key: row[0] for key, row in looks.LOOKS.items() if key is not LookKey.IDLE}
    by_status = {k: c for k, c in lit.items() if k is not LookKey.DANCE}
    assert len(set(by_status.values())) == len(by_status)
    assert lit[LookKey.DANCE] not in set(by_status.values())


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


EVERYTHING_ELSE = {
    "pairing": True,
    "offline": True,
    "fault": True,
    "battery_low": True,
    "dancing": True,
    "funnel": FunnelState.LISTENING,
}


def test_the_priority_order_is_live_camera_pairing_attention_listening_dance():
    assert resolve_key(_request(live=True, camera=True, **EVERYTHING_ELSE)) is LookKey.LIVE
    assert resolve_key(_request(camera=True, **EVERYTHING_ELSE)) is LookKey.CAMERA
    assert resolve_key(_request(**EVERYTHING_ELSE)) is LookKey.PAIRING
    rest = {k: v for k, v in EVERYTHING_ELSE.items() if k != "pairing"}
    assert resolve_key(_request(**rest)) is LookKey.ATTENTION
    rest = {k: v for k, v in rest.items() if k not in ("offline", "fault", "battery_low")}
    assert resolve_key(_request(**rest)) is LookKey.LISTENING
    assert resolve_key(_request(dancing=True)) is LookKey.DANCE
    assert resolve_key(_request()) is None


def test_the_privacy_cues_win_asleep_at_night_and_with_the_lights_off():
    off = IndicatorSettings(enabled=False)
    for extra in ({"asleep": True}, {"dark_room": True}, {"minute": NIGHT_MINUTE}):
        assert resolve_key(_request(live=True, **extra)) is LookKey.LIVE
        assert resolve_key(_request(camera=True, **extra)) is LookKey.CAMERA
    assert resolve_key(_request(live=True, settings=off, asleep=True)) is LookKey.LIVE


@pytest.mark.parametrize("state", [FunnelState.THINKING, FunnelState.SPEAKING, FunnelState.IDLE])
def test_thinking_speaking_and_idle_are_dark(state):
    assert resolve(_request(funnel=state)) is None
    assert resolve(_request(funnel=state, minute=NIGHT_MINUTE)) is None


def test_listening_is_blue_steady_at_the_level():
    look = resolve(
        _request(funnel=FunnelState.LISTENING, settings=IndicatorSettings(brightness=0.8))
    )
    assert look.colour is Palette.BLUE and look.style is LookStyle.STEADY
    assert look.brightness == pytest.approx(0.8)


def test_removed_states_have_no_fact_and_no_key():
    removed = {"alarm", "held", "muted", "offer", "sleep", "thinking", "speaking", "charging"}
    removed |= {"connecting", "updating", "error", "offline", "battery_low", "alarm_dim"}
    removed |= {"sees_maybe", "sees_person", "sees_face", "dancing"}
    assert not removed & {key.value for key in LookKey}
    fields = set(LookRequest.__dataclass_fields__)
    assert not fields & {"charging", "connecting", "updating", "sees", "alarm", "held", "muted"}


def test_the_one_amber_covers_offline_a_fault_and_a_low_battery():
    looks_seen = [
        resolve(_request(**{cause: True})) for cause in ("offline", "fault", "battery_low")
    ]
    assert looks_seen[0] == looks_seen[1] == looks_seen[2]
    look = looks_seen[0]
    assert look.colour is Palette.AMBER
    assert look.style is LookStyle.PULSE
    assert look.period_s == 10.0
    assert look.brightness == pytest.approx(0.3)


@pytest.mark.parametrize(
    "settings", [IndicatorSettings(brightness=0.2), IndicatorSettings(brightness=1.0)]
)
def test_attention_and_pairing_are_fixed_brightness_not_scaled_by_the_level(settings):
    assert resolve(_request(offline=True, settings=settings)).brightness == pytest.approx(0.3)
    assert resolve(_request(pairing=True, settings=settings)).brightness == pytest.approx(0.6)


def test_attention_is_dark_at_night_and_asleep_pairing_is_dark_asleep():
    assert resolve(_request(offline=True, minute=NIGHT_MINUTE)) is None
    assert resolve(_request(battery_low=True, dark_room=True)) is None
    assert resolve(_request(offline=True, asleep=True)) is None
    assert resolve(_request(pairing=True, asleep=True)) is None
    assert resolve(_request(pairing=True, minute=NIGHT_MINUTE)) is not None


def test_a_disabled_indicator_shows_nothing_but_the_capture_cues():
    off = IndicatorSettings(enabled=False)
    for kwargs in ({"funnel": FunnelState.LISTENING}, {"offline": True}, {"pairing": True}):
        assert resolve(_request(settings=off, **kwargs)) is None
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


def test_a_dark_room_uses_the_night_level_like_quiet_hours():
    night = resolve(_request(funnel=FunnelState.LISTENING, minute=NIGHT_MINUTE))
    dark = resolve(_request(funnel=FunnelState.LISTENING, dark_room=True))
    assert dark == night


@pytest.mark.parametrize("presence", [[CHILD], [TEEN], [UNKNOWN], None])
def test_a_child_teen_unknown_or_missing_presence_gets_the_lowest_night_level(presence):
    adult = resolve(_request(funnel=FunnelState.LISTENING, minute=NIGHT_MINUTE))
    other = resolve(_request(funnel=FunnelState.LISTENING, minute=NIGHT_MINUTE, presence=presence))
    assert other.brightness < adult.brightness


def test_nobody_present_is_not_unknown():
    adult = resolve(_request(funnel=FunnelState.LISTENING, minute=NIGHT_MINUTE, presence=[ADULT]))
    empty = resolve(_request(funnel=FunnelState.LISTENING, minute=NIGHT_MINUTE, presence=[]))
    assert empty.brightness == adult.brightness


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


def test_resolve_key_agrees_with_resolve_over_a_seeded_sweep():
    flags = ["live", "camera", "fault", "pairing", "offline", "battery_low", "dancing", "asleep"]
    rng = random.Random(20)
    for _ in range(3000):
        kwargs = {flag: rng.random() < 0.5 for flag in flags}
        kwargs["dark_room"] = rng.random() < 0.3
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


def test_period_s_uses_the_override_then_the_style():
    assert looks.period_s(LookKey.PAIRING) == 2.0
    assert looks.period_s(LookKey.ATTENTION) == 10.0
    assert looks.period_s(LookKey.CAMERA) == 0.5
    assert looks.period_s(LookKey.LIVE) == 0.0


def test_camera_is_pink_flash_at_its_floor_even_night_with_a_child():
    settings = IndicatorSettings(brightness=0.2, night_brightness=0.0)
    look = resolve(_request(camera=True, settings=settings, minute=NIGHT_MINUTE, presence=[CHILD]))
    assert look is not None
    assert look.colour is Palette.PINK
    assert look.style is LookStyle.FLASH
    assert look.brightness >= looks.CAMERA_FLOOR


def test_the_ring_has_one_writer_the_light_service():
    """No ring write outside the service's own wiring: the night controller, app.py and the
    camera and notification paths tell the service facts and never write a pixel."""
    for relative in ("app.py", "presence/night.py"):
        text = (PACKAGE / relative).read_text()
        assert re.findall(r"leds\.many\(|\.set_led_colors?\(", text) == [], relative
    adapter = (PACKAGE / "bodies" / "stackchan" / "adapter.py").read_text()
    # The only ring calls left in the adapter are the LED part's own driver and the raw client
    # pass-through; the camera driver and the alert path make none, and keep no second RGB.
    assert adapter.count("client.set_led_colors(") == 1  # _LedAdapter.many, the part's driver
    assert adapter.count("client.set_led_color(") == 1  # the raw client pass-through
    assert "(168, 36, 0)" not in adapter and "_camera_rgb" not in adapter
    assert "leds.many(" not in adapter.replace("leds.many with", "").replace("leds.many needs", "")
