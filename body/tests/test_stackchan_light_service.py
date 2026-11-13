"""The StackChan light service: facts in, one ring look out.

Covers docs/dev/led-standard-2026-10-20.md ("The ring table"): the service
re-resolves one look from the one table (``indicator/looks.py``) on every
change and every 60 s refresh, holds the live and camera cues for at
least ``CUE_HOLD_S`` once raised, and never lets a failing indicator
break the voice or camera path.
"""

from __future__ import annotations

import threading
import time

import pytest

from maipai_body.bodies.stackchan.light_service import StackChanLightService
from maipai_body.hal.seam import Look, LookStyle, Palette
from maipai_body.indicator import looks
from maipai_body.indicator.settings import IndicatorSettings
from maipai_body.presence.carry_reaction import PresenceEntry
from maipai_body.presence.funnel import FunnelState

DAY = 12 * 60
NIGHT = 23 * 60


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class FakeRing:
    """A recording stand-in for StackChanRingIndicator."""

    def __init__(self) -> None:
        self.looks: list[Look | None] = []
        self.ticks = 0
        self.current: Look | None = None

    def set_look(self, look: Look) -> None:
        self.looks.append(look)
        self.current = look

    def off(self) -> None:
        self.looks.append(None)
        self.current = None

    def tick(self) -> None:
        self.ticks += 1


def _service(*, settings=None, presence=None, minute=DAY, funnel=None):
    clock = Clock()
    ring = FakeRing()
    state = {
        "settings": settings or IndicatorSettings(),
        "presence": presence,
        "minute": minute,
    }
    service = StackChanLightService(
        ring,
        settings=lambda: state["settings"],
        presence=lambda: state["presence"],
        minute=lambda: state["minute"],
        clock=clock,
    )
    if funnel is not None:
        service.update(funnel=funnel)
    return service, ring, clock, state


def test_idle_facts_leave_the_ring_dark():
    service, ring, _, _ = _service()
    service.refresh()
    assert ring.current is None


def test_live_shows_green_and_outranks_everything():
    service, ring, _, _ = _service(funnel=FunnelState.SPEAKING)
    service.update(fault=True, offline=True, pairing=True, battery_low=True)
    service.cue_live(True)
    assert ring.current is not None
    assert ring.current.colour is Palette.GREEN
    assert ring.current.brightness >= looks.LIVE_FLOOR


def test_the_live_cue_is_held_for_the_floor_after_lowering():
    service, ring, clock, _ = _service()
    service.cue_live(True)
    assert ring.current is not None and ring.current.colour is Palette.GREEN
    clock.now += 0.1
    service.cue_live(False)
    assert ring.current is not None and ring.current.colour is Palette.GREEN
    clock.now += looks.CUE_HOLD_S
    service.tick()
    assert ring.current is None or ring.current.colour is not Palette.GREEN


def test_the_camera_cue_is_held_for_the_floor_after_lowering():
    service, ring, clock, _ = _service()
    service.cue_camera(True)
    assert ring.current is not None and ring.current.colour is Palette.PINK
    clock.now += 0.1
    service.cue_camera(False)
    assert ring.current is not None and ring.current.colour is Palette.PINK
    clock.now += looks.CUE_HOLD_S
    service.refresh()
    assert ring.current is None or ring.current.colour is not Palette.PINK


def test_camera_shows_a_pink_flash_above_the_floor_at_night_with_a_child():
    settings = IndicatorSettings(night_from=20 * 60, night_to=8 * 60)
    service, ring, _, _ = _service(
        settings=settings, presence=[PresenceEntry("child")], minute=NIGHT
    )
    service.update(camera=True)
    look = ring.current
    assert look is not None
    assert look.colour is Palette.PINK
    assert look.style is LookStyle.FLASH
    assert look.brightness >= looks.CAMERA_FLOOR


def test_thinking_speaking_and_charging_leave_the_ring_dark():
    service, ring, _, _ = _service()
    for state in (FunnelState.THINKING, FunnelState.SPEAKING, FunnelState.IDLE):
        service.update(funnel=state)
        assert ring.current is None


def test_charging_is_not_a_ring_fact():
    service, ring, _, _ = _service()
    with pytest.raises(TypeError):
        service.update(charging=True)
    assert ring.current is None


def test_the_one_amber_serves_battery_low_offline_and_a_fault():
    for fact in ("battery_low", "offline", "fault"):
        service, ring, _, _ = _service()
        service.update(**{fact: True})
        look = ring.current
        assert look is not None
        assert look.colour is Palette.AMBER
        assert look.style is LookStyle.PULSE
        assert look.period_s == looks.period_s(looks.LookKey.ATTENTION) == 10.0
        assert look.brightness == pytest.approx(0.3)


def test_the_amber_pulse_is_one_short_flash_every_ten_seconds_on_the_real_ring():
    from maipai_body.bodies.stackchan.ring_indicator import StackChanRingIndicator

    writes: list[tuple[float, tuple[int, int, int]]] = []
    clock = Clock()
    indicator = StackChanRingIndicator(lambda rgb: writes.append((clock.now, rgb)), clock=clock)
    service = StackChanLightService(indicator, minute=lambda: DAY, clock=clock)
    service.update(offline=True)
    start = clock.now
    for _ in range(int(25.0 / 0.05)):
        clock.now += 0.05
        service.tick()
    lit = [(round(t - start, 2), rgb) for t, rgb in writes if rgb != (0, 0, 0)]
    dark = [(round(t - start, 2), rgb) for t, rgb in writes if rgb == (0, 0, 0)]
    assert [t for t, _ in lit] == pytest.approx([0.0, 10.0, 20.0], abs=0.06)  # every 10 s
    assert all(rgb == (50, 23, 0) for _, rgb in lit)  # amber at 0.3 of the channel maximum
    assert 0.2 <= dark[0][0] <= 0.35  # and each one is short (about a quarter second)


def test_pairing_shows_a_cyan_pulse():
    service, ring, _, _ = _service()
    service.update(pairing=True)
    look = ring.current
    assert look is not None
    assert look.colour is Palette.CYAN
    assert look.style is LookStyle.PULSE
    assert look.period_s == 2.0


def test_asleep_is_dark_and_waking_does_not_relight_the_ring():
    for minute in (DAY, NIGHT):
        service, ring, _, _ = _service(minute=minute)
        service.set_sleeping(True)
        service.update(offline=True)
        assert ring.current is None
        service.set_sleeping(False)
        assert ring.current is None or minute == DAY  # attention may show by day, never a glow
        service.update(offline=False)
        assert ring.current is None


def test_waking_by_day_shows_no_idle_or_sleep_glow():
    service, ring, _, _ = _service()
    service.set_sleeping(True)
    service.set_sleeping(False)
    assert ring.current is None
    assert ring.looks[-1] is None


def test_asleep_still_shows_the_capture_cues():
    service, ring, _, _ = _service()
    service.set_sleeping(True)
    service.cue_camera(True)
    assert ring.current is not None and ring.current.colour is Palette.PINK
    service.cue_live(True)
    assert ring.current.colour is Palette.GREEN


def test_a_dark_room_is_dark_like_night_and_ends_dark():
    service, ring, _, _ = _service()
    service.update(offline=True)
    assert ring.current is not None
    service.set_dark_room(True)
    assert ring.current is None
    service.set_dark_room(False)
    assert ring.current is not None  # amber is back by day: the room, not the ring, was dark


def test_the_night_by_the_clock_darkens_the_attention_row():
    service, ring, _, state = _service()
    service.update(battery_low=True)
    assert ring.current is not None
    state["minute"] = NIGHT
    service.refresh()
    assert ring.current is None


def test_disabled_settings_darken_everything_but_the_cues():
    service, ring, _, _ = _service(settings=IndicatorSettings(enabled=False))
    service.refresh()
    assert ring.current is None
    service.update(fault=True, pairing=True, offline=True)
    assert ring.current is None
    service.cue_live(True)
    assert ring.current is not None
    assert ring.current.colour is Palette.GREEN


def test_a_failing_indicator_never_propagates():
    class BrokenRing:
        def set_look(self, look: Look) -> None:
            raise OSError("i2c gone")

        def off(self) -> None:
            raise OSError("i2c gone")

        def tick(self) -> None:
            return None

    service = StackChanLightService(BrokenRing())
    service.refresh()
    service.update(fault=True)
    service.cue_live(True)
    service.cue_camera(True)
    service.tick()


def test_run_ticks_and_stops_on_the_event_ending_off():
    ring = FakeRing()
    service = StackChanLightService(ring)
    stop = threading.Event()
    thread = threading.Thread(
        target=service.run,
        args=(stop,),
        kwargs={"tick_s": 0.001},
        daemon=True,
    )
    thread.start()
    time.sleep(0.02)
    stop.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert ring.ticks > 0
    assert ring.looks[-1] is None


def test_an_unknown_update_field_raises_type_error():
    service, _, _, _ = _service()
    with pytest.raises(TypeError):
        service.update(not_a_fact=True)


def test_the_vision_glow_is_gone():
    service, _, _, _ = _service()
    with pytest.raises(TypeError):
        service.update(sees="face")
