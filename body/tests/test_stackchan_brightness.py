"""Spoken brightness and the hub's default volume and brightness (owner request 2026-10-21)."""

from __future__ import annotations

import pytest

from maipai_body.bodies.stackchan.brightness import (
    MIN_LEVEL,
    BrightnessCommand,
    BrightnessControl,
    confirmation,
    next_level,
    parse_brightness_command,
)
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.owner_levels import OwnerLevels
from maipai_body.presence.night import NIGHT_BRIGHTNESS, NightController


@pytest.mark.parametrize(
    ("text", "kind", "level"),
    [
        ("set brightness to 50%", "set", 50),
        ("Brightness 100", "set", 100),
        ("set the brightness to seventy", "set", 70),
        ("make it brighter", "up", None),
        ("a little bit dimmer please", "down", None),
        ("make it darker", "down", None),
        ("it's too bright", "down", None),
        ("it's too dark", "up", None),
        ("dim your screen", "down", None),
        ("full brightness", "max", None),
        ("brightness", "ask", None),
        ("screen off", "off", None),
        ("turn off the screen", "off", None),
        ("brightness is weird", "hint", None),
    ],
)
def test_brightness_phrases_are_recognised(text, kind, level):
    command = parse_brightness_command(text)
    assert command == BrightnessCommand(kind, level)


@pytest.mark.parametrize(
    "text",
    [
        "volume to 50",
        "turn the volume up",
        "what is the weather",
        "dim the lights in the kitchen",
        "tell me about dark matter in the galaxy and how it is distributed",
    ],
)
def test_other_sentences_are_left_alone(text):
    assert parse_brightness_command(text) is None


def test_the_screen_never_goes_below_the_floor():
    assert next_level(30, BrightnessCommand("set", 0)) == MIN_LEVEL
    assert next_level(MIN_LEVEL, BrightnessCommand("down")) == MIN_LEVEL
    assert next_level(90, BrightnessCommand("up")) == 100
    assert next_level(40, BrightnessCommand("off")) == 40
    assert confirmation(BrightnessCommand("set", 50), 100, 50) == "Brightness 50."
    assert confirmation(BrightnessCommand("down"), 10, 10) == "That is as dim as I go."


def _rig(tmp_path):
    levels = OwnerLevels(tmp_path / "levels.json")
    levels.load()
    device = FakeStackChanDeviceClient()
    clock = [0.0]
    quiet = [False]
    night = NightController(
        device, clock=lambda: clock[0], quiet_hours=lambda: quiet[0], levels=levels
    )
    return levels, device, night, clock, quiet


def test_voice_brightness_by_day_updates_the_owner_level(tmp_path):
    levels, device, night, _clock, _quiet = _rig(tmp_path)
    control = BrightnessControl(night.effective_brightness, night.set_brightness_from_voice)
    assert control.apply(BrightnessCommand("set", 40)) == (100, 40)
    assert levels.brightness == 40 and device.brightness == 40


def test_voice_brightness_at_night_is_the_night_level_and_day_restores_exactly(tmp_path):
    levels, device, night, clock, quiet = _rig(tmp_path)
    night.set_brightness_from_voice(70)
    quiet[0] = True
    night.tick()
    assert device.brightness == NIGHT_BRIGHTNESS
    night.set_brightness_from_voice(30)
    assert device.brightness == 30 and levels.brightness == 70
    quiet[0] = False
    device.ambient_lux = 100
    night.tick()  # light starts counting
    clock[0] = 120
    night.tick()
    assert device.brightness == 70 and night.night_brightness_override is None


def test_hub_defaults_become_owner_levels_once_and_day_only(tmp_path):
    levels, device, night, _clock, quiet = _rig(tmp_path)
    night.apply_settings({"robot.volume": 55, "robot.brightness": 60})
    assert (levels.volume, levels.brightness) == (55, 60)
    assert device.volume == 55 and device.brightness == 60
    night.set_brightness_from_voice(35)
    night.apply_settings({"robot.volume": 55, "robot.brightness": 60})  # repeated: not new
    assert levels.brightness == 35
    reloaded = OwnerLevels(tmp_path / "levels.json")
    reloaded.load()
    assert (reloaded.hub_volume, reloaded.hub_brightness) == (55, 60)
    quiet[0] = True
    night.tick()
    night.apply_settings({"robot.brightness": 80})
    assert levels.brightness == 80 and device.brightness == NIGHT_BRIGHTNESS


def test_bad_hub_values_are_ignored(tmp_path):
    levels, _device, night, _clock, _quiet = _rig(tmp_path)
    night.apply_settings({"robot.volume": "loud", "robot.brightness": True})
    assert (levels.volume, levels.brightness) == (70, 100)


def test_the_bridge_answers_a_brightness_command_without_asking_the_hub(monkeypatch):
    import asyncio

    import maipai_body.bodies.stackchan.turn as turn_module
    from maipai_body.speech.stt_stream import SttStreamResult
    from tests.test_stackchan_turn import (  # type: ignore[import-not-found]
        FakeCapture,
        FakePlayback,
        FakeServer,
        FakeTts,
        FakeTurn,
        InlineExecutor,
        Link,
        Offline,
    )

    class DimStt:
        def __init__(self, base, cookie):
            pass

        def run(self, capture, **kwargs):
            return SttStreamResult(kind="final", text="Set brightness to 50 percent")

    set_to: list[int] = []
    control = BrightnessControl(lambda: 100, set_to.append)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    FakeTurn.streams = []
    FakeTts.sentences = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    bridge = turn_module.StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=DimStt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
        brightness_control=control,
    )
    loop.run_until_complete(bridge._run("session", "device", FakeCapture()))
    loop.close()
    assert set_to == [50]
    assert FakeTurn.streams == []
    assert FakeTts.sentences == ["Brightness 50."]


def test_the_units_own_sliders_sync_the_owner_levels_by_day_and_the_night_levels_at_night(tmp_path):
    levels, device, night, _clock, quiet = _rig(tmp_path)
    night.set_levels_from_unit(45, 60)
    assert (levels.volume, levels.brightness) == (45, 60)
    quiet[0] = True
    night.tick()
    night.set_levels_from_unit(10, 20)
    assert (levels.volume, levels.brightness) == (45, 60)
    assert night.effective_brightness() == 20 and night.night_volume_override == 10


def test_level_changed_events_are_kept_even_when_the_queue_is_only_being_drained():
    from types import SimpleNamespace

    from maipai_body.app import StackChanBehavior
    from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter

    behavior = StackChanBehavior(StackChanRobotAdapter(FakeStackChanDeviceClient()).robot)
    seen = []
    reactions = []
    try:
        behavior._rest = type("Rest", (), {"stage": "awake"})()
        behavior.reaction = reactions.append
        behavior.on_levels_changed = lambda volume, brightness: seen.append((volume, brightness))
        batch = [SimpleNamespace(kind="level_changed", volume=40, brightness=None)]
        behavior.event_poll = lambda: batch
        assert behavior.wake_on_touch(0.0) is False  # the first look drains, levels still kept
        assert seen == [(40, None)] and reactions == []
    finally:
        behavior.close()


def test_companion_reads_the_level_changed_event():
    from maipai_body.bodies.stackchan.companion import StackChanCompanion

    companion = StackChanCompanion(
        lambda name, args: [
            {"kind": "level_changed", "at_ms": 5, "volume": 55, "brightness": 300},
            {"kind": "shake", "at_ms": 6},
        ]
    )
    first, second = companion.poll_events()
    assert (first.volume, first.brightness) == (55, None)  # 300 is not a percent: dropped
    assert (second.volume, second.brightness) == (None, None)
