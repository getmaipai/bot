"""The StackChan's sounds on the host: the play_sound mapping, night and mute gating, quiet hours,
the host-owned cues, the assets and the sound self-test (firmware patches 115 to 118)."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

import pytest

from maipai_body.bodies.stackchan import sounds as sounds_module
from maipai_body.bodies.stackchan.sounds import (
    CHIME_ALLOWED,
    CHIME_GAP_S,
    EARCONS,
    LOW_BATTERY_LINE,
    NIGHT_OK,
    SECONDS,
    SoundService,
)
from maipai_body.presence.sleep_auto import QuietHours
from maipai_body.settings_keys import MUTED_KEY, QUIET_KEY, SOUNDS_ENABLED_KEY, SOUNDS_NIGHT_KEY


@pytest.fixture(autouse=True)
def _normal_policy(monkeypatch):
    """The older tests describe the normal policy; the silenced default has its own tests below."""
    monkeypatch.setattr(sounds_module, "SILENCE_UNIT_SOUNDS", False)


HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent / "maipai_body/bodies/stackchan/firmware"
SOUNDS = FIRMWARE / "assets/sounds"
PHRASES = FIRMWARE / "assets/phrases"
CORE = (FIRMWARE / "patches/115-sounds-core.patch").read_text()


class Unit:
    """A fake unit: records tool calls and answers like the firmware's gate would."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.answer: object = '{"ok":true}'
        self.error: Exception | None = None

    def __call__(self, name: str, arguments: dict) -> object:
        self.calls.append((name, dict(arguments)))
        if self.error is not None:
            raise self.error
        return self.answer

    def played(self) -> list[str]:
        return [a["name"] for n, a in self.calls if n == "self.audio.play_sound"]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make(**kwargs):
    unit = Unit()
    clock = Clock()
    said: list[str] = []
    state = {"night": False, "low": False, "say_ok": True}

    def say(text: str) -> bool:
        if not state["say_ok"]:
            return False
        said.append(text)
        return True

    service = SoundService(
        unit,
        say=say,
        night=lambda: state["night"],
        battery_low=lambda: state["low"],
        run_async=lambda job: job(),
        clock=clock,
        sleep=clock.sleep,
        **kwargs,
    )
    return service, unit, clock, said, state


# ---- the name list and the rules are the firmware's ----


def _c_names() -> list[str]:
    block = CORE.split("MS_SOUND_NAMES[MS_SND_COUNT] = {", 1)[1].split("};", 1)[0]
    return re.findall(r'"([a-z_]+)"', block)


def _c_night_ok() -> set[str]:
    enum = CORE.split("typedef enum {", 1)[1].split("} ms_sound_t;", 1)[0]
    idents = re.findall(r"\+?(MS_SND_[A-Z_]+)(?: = 0)?,", enum)
    idents = [i for i in idents if i != "MS_SND_COUNT"]
    names = dict(zip(idents, _c_names(), strict=True))
    block = CORE.split("static inline int ms_night_ok(int snd, int urgent)", 1)[1]
    block = block.split("case MS_SND_NEEDS_YOU:", 1)[0]
    return {names[i] for i in re.findall(r"case (MS_SND_[A-Z_]+):", block)}


def test_the_host_list_is_the_firmware_list_in_order():
    assert list(EARCONS) == _c_names()
    assert len(EARCONS) == 12


def test_the_host_night_rule_is_the_firmware_night_rule():
    assert set(NIGHT_OK) == _c_night_ok()


def test_the_wait_table_covers_every_sound_and_matches_the_rendered_files():
    assert set(SECONDS) == set(EARCONS)
    manifest = json.loads((SOUNDS / "sounds.json").read_text())["earcons"]
    for name, row in manifest.items():
        assert abs(SECONDS[name] - row["seconds"]) <= 0.05, name


# ---- play: the mapping and the gate ----


def test_play_sends_the_name_the_urgent_flag_and_the_test_flag():
    service, unit, *_ = make()
    assert service.play("plug_in").ok
    assert unit.calls == [
        ("self.audio.play_sound", {"name": "plug_in", "urgent": False, "test": False})
    ]


def test_every_name_in_the_list_can_be_played_by_day_when_the_firmware_says_yes():
    service, unit, *_ = make()
    for name in EARCONS:
        # a sound test (test=True) bypasses the chime gate; routine cues are refused without it
        assert service.play(name, test=True).ok, name
    assert unit.played() == list(EARCONS)


def test_an_unknown_name_is_refused_before_the_unit_is_asked():
    service, unit, *_ = make()
    result = service.play("trumpet")
    assert (result.ok, result.reason) == (False, "unknown_sound")
    assert unit.calls == []


def test_the_units_own_refusal_comes_back_as_the_reason():
    service, unit, *_ = make()
    unit.answer = '{"ok":false,"error":"night"}'
    result = service.play("success", test=True)
    assert (result.ok, result.reason) == (False, "night")


def test_an_unreachable_or_old_unit_is_reported_not_raised():
    service, unit, *_ = make()
    unit.error = RuntimeError("StackChan did not complete self.audio.play_sound")
    assert service.play("plug_in").reason == "unreachable"
    unit.error = RuntimeError("StackChan does not support x: unknown tool")
    assert service.play("plug_in", test=True).reason == "unsupported"


def test_at_night_only_the_safety_and_answering_cues_are_asked():
    service, unit, _, _, state = make()
    state["night"] = True
    for name in EARCONS:
        result = service.play(name)
        assert result.ok == (name in NIGHT_OK and name in CHIME_ALLOWED), name
        if not result.ok:
            assert result.reason in ("night", "not_allowed")
    assert set(unit.played()) == set(NIGHT_OK) & CHIME_ALLOWED
    assert {"shutter", "goodbye", "low_battery", "exclamation"} <= set(NIGHT_OK)
    assert not {"plug_in", "charged", "unplug", "offline", "success", "needs_you"} & set(NIGHT_OK)


def test_first_setup_needs_you_passes_at_night_but_the_approval_one_does_not():
    service, unit, _, _, state = make()
    state["night"] = True
    assert service.play("needs_you").reason == "night"
    assert service.play("needs_you", urgent=True).ok
    assert unit.calls[-1][1]["urgent"] is True


def test_the_night_setting_lets_event_sounds_play_at_night():
    service, unit, _, _, state = make()
    state["night"] = True
    service.apply_settings({SOUNDS_NIGHT_KEY: True})
    assert service.play("plug_in").ok


def test_sounds_off_keeps_only_a_picture_and_the_urgent_setup_cue():
    service, unit, *_ = make()
    service.apply_settings({SOUNDS_ENABLED_KEY: False})
    assert service.play("plug_in").reason == "disabled"
    assert service.play("low_battery").reason == "disabled"
    assert service.play("shutter").ok
    assert service.play("needs_you", urgent=True).ok
    assert service.play("needs_you").reason == "disabled"


@pytest.mark.parametrize("key", [MUTED_KEY, QUIET_KEY])
def test_the_hard_mute_silences_everything_a_picture_and_the_self_test_included(key):
    service, unit, *_ = make()
    service.apply_settings({key: True})
    unit.calls.clear()
    for name in EARCONS:
        assert service.play(name).reason == "muted"
        assert service.play(name, test=True).reason == "muted"
    assert unit.calls == []
    service.apply_settings({key: False})
    assert service.play("shutter").ok


def test_the_self_test_skips_the_off_switch_and_the_night_rule_but_not_the_mute():
    service, unit, _, _, state = make()
    service.apply_settings({SOUNDS_ENABLED_KEY: False})
    state["night"] = True
    assert service.play("plug_in", test=True).ok
    assert unit.calls[-1][1]["test"] is True


# ---- the policy the unit applies on its own ----


def test_the_policy_carries_quiet_hours_as_minutes_and_the_sensor_night():
    hours = QuietHours()
    hours.apply({"household.quiet_hours.from": "22:30", "household.quiet_hours.to": "06:15"})
    service, unit, _, _, state = make(quiet_minutes=hours.minutes)
    state["night"] = True
    assert service.push_policy()
    name, arguments = unit.calls[-1]
    assert name == "self.audio.set_sound_policy"
    assert arguments == {
        "enabled": True,
        "night_ok": False,
        "muted": False,
        "dark": True,
        "quiet_from": 22 * 60 + 30,
        "quiet_to": 6 * 60 + 15,
    }


def test_quiet_hours_minutes_are_empty_when_the_bounds_are_equal():
    hours = QuietHours()
    hours.apply({"household.quiet_hours.from": "07:00", "household.quiet_hours.to": "07:00"})
    assert hours.minutes() == (-1, -1)
    assert QuietHours().minutes() == (21 * 60, 7 * 60)  # the registry defaults


def test_full_quiet_goes_to_the_unit_as_a_mute():
    service, unit, *_ = make()
    service.apply_settings({QUIET_KEY: True})
    assert unit.calls[-1][1]["muted"] is True


def test_the_policy_is_pushed_once_until_it_changes_and_again_after_a_reconnect():
    service, unit, clock, _, state = make()
    service.push_policy()
    service.push_policy()
    assert len(unit.calls) == 1
    state["night"] = True  # the sensor says night: the unit is told
    service.push_policy()
    assert len(unit.calls) == 2
    service.on_connect()  # the unit rebooted: told again at once
    assert len(unit.calls) == 3
    clock.now += sounds_module.POLICY_EVERY_S + 1  # and refreshed now and then
    service.push_policy()
    assert len(unit.calls) == 4


def test_a_failed_push_waits_before_the_next_try():
    service, unit, clock, *_ = make()
    unit.error = ConnectionError("away")
    assert not service.push_policy()
    assert not service.push_policy()
    assert len(unit.calls) == 1
    clock.now += sounds_module.PUSH_RETRY_S + 1
    unit.error = None
    assert service.push_policy()
    assert len(unit.calls) == 2


# ---- the host-owned cues ----


def test_low_battery_plays_the_earcon_then_says_the_line_once_per_crossing():
    service, unit, clock, said, state = make()
    service.tick()
    assert unit.played() == [] and said == []
    state["low"] = True
    service.tick()
    assert unit.played() == ["low_battery"]
    assert said == [LOW_BATTERY_LINE]
    for _ in range(5):
        service.tick()
    assert unit.played() == ["low_battery"] and said == [LOW_BATTERY_LINE]
    state["low"] = False  # charged a little
    service.tick()
    state["low"] = True  # a second crossing a minute later (a crossing within the gap stays silent)
    clock.now += CHIME_GAP_S + 1
    service.tick()
    assert unit.played() == ["low_battery", "low_battery"]
    assert said == [LOW_BATTERY_LINE, LOW_BATTERY_LINE]


def test_low_battery_at_night_is_the_earcon_only():
    service, unit, _, said, state = make()
    state["night"] = True
    state["low"] = True
    service.tick()
    assert unit.played() == ["low_battery"]
    assert said == []


def test_the_low_battery_line_waits_for_a_free_robot_then_gives_up():
    service, unit, clock, said, state = make()
    state["low"] = True
    state["say_ok"] = False  # a turn is going on
    service.tick()
    clock.now += 10
    service.tick()
    assert said == []
    state["say_ok"] = True
    clock.now += 5
    service.tick()
    assert said == [LOW_BATTERY_LINE]
    # and a robot that stays busy past the limit never says it late
    service2, unit2, clock2, said2, state2 = make()
    state2["low"] = True
    state2["say_ok"] = False
    service2.tick()
    clock2.now += sounds_module.SPEAK_FOR_S + 1
    state2["say_ok"] = True
    service2.tick()
    assert said2 == []


def test_low_battery_line_is_skipped_when_muted_or_off():
    service, unit, _, said, state = make()
    service.apply_settings({SOUNDS_ENABLED_KEY: False})
    state["low"] = True
    service.tick()
    assert said == [] and unit.played() == []


def test_the_shutter_clicks_once_per_picture_even_at_night():
    service, unit, clock, _, state = make()
    state["night"] = True
    service.on_camera_cue(True)
    service.on_camera_cue(True)  # the cue repeats while the picture is up
    assert unit.played() == ["shutter"]
    service.on_camera_cue(False)
    clock.now += 5
    service.on_camera_cue(True)
    assert unit.played() == ["shutter", "shutter"]


def test_a_flapping_cue_does_not_machine_gun_the_shutter():
    service, unit, clock, *_ = make()
    for _ in range(5):
        service.on_camera_cue(True)
        service.on_camera_cue(False)
        clock.now += 0.2
    assert unit.played() == ["shutter"]


def test_the_error_cue_and_no_dance_chime():
    service, unit, clock, _, state = make()
    service.on_error_line()
    assert unit.played() == ["exclamation"]
    assert not hasattr(service, "on_dance_start")  # nothing chimes for a dance (owner 2026-11-14)
    unit.calls.clear()
    clock.now += CHIME_GAP_S + 1
    state["night"] = True
    service.on_error_line()  # the earcon only at night
    assert unit.played() == ["exclamation"]


# ---- the chime gate (owner 2026-11-14: rules for when to chime)


def test_only_the_allowed_cues_chime_and_routine_ones_are_refused():
    service, unit, *_ = make()
    for name in ("success", "popup", "vibration", "offline"):
        result = service.play(name)
        assert (result.ok, result.reason) == (False, "not_allowed"), name
    assert unit.played() == []
    assert CHIME_ALLOWED == {
        "needs_you",
        "plug_in",
        "unplug",
        "charged",
        "low_battery",
        "shutter",
        "goodbye",
        "exclamation",
    }


def test_a_flapping_event_makes_at_most_one_chime_per_gap():
    service, unit, clock, *_ = make()
    for _ in range(30):  # a state that flaps every 5 s for 150 s
        service.play_later("needs_you")
        clock.now += 5.0
    assert unit.played().count("needs_you") == 3  # 0 s, 65 s, 130 s with a 60 s gap
    clock.now += CHIME_GAP_S
    assert service.play("needs_you").ok


def test_a_cue_has_a_daily_cap_and_a_sound_test_bypasses_the_gate():
    service, unit, clock, *_ = make()
    for _ in range(40):
        clock.now += CHIME_GAP_S + 1
        service.play("charged")
    assert unit.played().count("charged") == 20
    assert service.play("charged", test=True).ok  # the self-test plays every sound
    clock.now += 24 * 3600
    assert service.play("charged").ok


def test_every_host_play_goes_through_the_chime_gate():
    source = Path(sounds_module.__file__).read_text()
    # the only place the host asks the unit to play a sound is SoundService.play, behind the gate
    assert source.count('"self.audio.play_sound"') == 1
    assert "_chime_gate(name)" in source


# ---- the sound self-test ----


def test_the_self_test_plays_every_sound_in_turn_and_waits_for_each():
    service, unit, clock, *_ = make()
    outcome = service.self_test()
    assert outcome == {"played": list(EARCONS), "failed": []}
    assert unit.played() == list(EARCONS)
    assert len(clock.slept) == len(EARCONS)
    assert all(slept >= SECONDS[name] for slept, name in zip(clock.slept, EARCONS, strict=True))
    assert all(a["test"] for n, a in unit.calls if n == "self.audio.play_sound")


def test_the_self_test_stops_and_says_why_when_muted_or_the_unit_is_away():
    service, unit, *_ = make()
    service.apply_settings({MUTED_KEY: True})
    outcome = service.self_test()
    assert outcome["played"] == []
    assert {row["reason"] for row in outcome["failed"]} == {"muted"}
    assert [row["sound"] for row in outcome["failed"]] == list(EARCONS)
    service2, unit2, *_ = make()
    unit2.error = ConnectionError("away")
    outcome2 = service2.self_test()
    assert outcome2["played"] == [] and len(outcome2["failed"]) == len(EARCONS)
    assert len(unit2.calls) == 1  # it did not knock twelve times


def test_the_sound_test_command_starts_the_test_and_answers_at_once(monkeypatch):
    service, unit, *_ = make()
    ran: list[str] = []
    monkeypatch.setattr(service, "_run_test", lambda: ran.append("test"))
    handlers = service.handlers()
    assert set(handlers) == {"sound_test"}
    reply = handlers["sound_test"]({})
    assert reply == {"sound_test": "started", "sounds": list(EARCONS)}
    for thread in __import__("threading").enumerate():
        if thread.name == "stackchan-sound-test":
            thread.join(2)
    assert ran == ["test"]
    service.apply_settings({MUTED_KEY: True})
    assert handlers["sound_test"]({}) == {"sound_test": "refused", "why": "muted"}


# ---- the assets: the earcons and the offline phrases ----


def _ogg_packets(data: bytes) -> tuple[dict, list[bytes]]:
    pages = []
    i = 0
    while i < len(data):
        assert data[i : i + 4] == b"OggS"
        nseg = data[i + 26]
        segs = data[i + 27 : i + 27 + nseg]
        size = sum(segs)
        granule = struct.unpack("<q", data[i + 6 : i + 14])[0]
        pages.append((granule, data[i + 27 + nseg : i + 27 + nseg + size]))
        i += 27 + nseg + size
    head = pages[0][1]
    assert head[:8] == b"OpusHead"
    info = {"channels": head[9], "rate": struct.unpack("<I", head[12:16])[0]}
    packets = [body for _, body in pages[2:] if body]
    info["granule"] = pages[-1][0]
    return info, packets


def test_the_seven_earcons_are_in_the_family_format_and_size():
    manifest = json.loads((SOUNDS / "sounds.json").read_text())["earcons"]
    assert set(manifest) == set(EARCONS[:7])
    for name, row in manifest.items():
        data = (SOUNDS / f"snd_{name}.ogg").read_bytes()
        assert hashlib.sha256(data).hexdigest() == row["sha256"], name
        info, packets = _ogg_packets(data)
        assert info["channels"] == 1 and info["rate"] == 16000, name
        assert {p[0] for p in packets} == {0x58}, name  # 60 ms frames, like the shipped tones
        assert 0.4 <= (info["granule"] - 312) / 48000 <= 1.0, name  # 0.4 to 1.0 s
        assert 400 <= len(data) <= 3500, name  # 0.5 to 3 KB like the shipped ones


def test_the_earcon_files_the_recipe_needs_all_exist():
    recipe = (FIRMWARE / "recipe.sh").read_text()
    names = re.search(r"for earcon in ([a-z_ ]+); do", recipe)
    assert names is not None
    assert names.group(1).split() == list(EARCONS[:7])
    for name in names.group(1).split():
        assert (SOUNDS / f"snd_{name}.ogg").is_file()


def _c_groups() -> tuple[list[str], list[int]]:
    names = re.search(r"MS_GROUP_NAMES\[MS_GRP_COUNT\] = \{([^}]*)\}", CORE)
    sizes = re.search(r"MS_GROUP_SIZE\[MS_GRP_COUNT\] = \{([^}]*)\}", CORE)
    assert names and sizes
    return re.findall(r'"([a-z_]+)"', names.group(1)), [int(n) for n in sizes.group(1).split(",")]


def test_the_sixteen_phrases_match_the_firmware_groups_and_the_files():
    names, sizes = _c_groups()
    assert sum(sizes) == 16
    doc = json.loads((PHRASES / "phrases.json").read_text())
    clips = doc["clips"]
    assert len(clips) == 16
    for group, count in zip(names, sizes, strict=True):
        rows = [c for c in clips if c["group"] == group]
        assert [c["variant"] for c in rows] == list(range(1, count + 1)), group
        assert len({c["text"] for c in rows}) == count  # no duplicate wording in a group
    for clip in clips:
        path = PHRASES / clip["file"]
        assert clip["file"] == f"ph_{clip['group']}_{clip['variant']}.ogg"
        assert len(clip["file"]) < 32  # the asset name limit
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == clip["sha256"], clip["file"]
        info, packets = _ogg_packets(data)
        assert info["channels"] == 1 and info["rate"] == 16000
        assert 0.5 <= (info["granule"] - 312) / 48000 <= 4.0, clip["file"]
        assert 1500 <= len(data) <= 9000, clip["file"]


def test_the_phrases_are_plain_words_a_child_can_follow():
    doc = json.loads((PHRASES / "phrases.json").read_text())
    for clip in doc["clips"]:
        assert clip["text"].endswith(".") and "—" not in clip["text"]
        assert len(clip["text"]) <= 45
    texts = " ".join(c["text"] for c in doc["clips"]).lower()
    assert "wi-fi" in texts and "approved" in texts and "connecting" in texts


def test_the_phrase_voice_record_names_the_licence_check():
    voice = json.loads((PHRASES / "phrases.json").read_text())["voice"]
    assert voice["licence_checked"] is True
    assert voice["licence"] == "Apache-2.0"
    assert voice["engine"] == "chatterbox-turbo" and voice["credit"]
    notice = (HERE.parent.parent / "NOTICE").read_text()
    assert "Chatterbox" in notice and "Apache-2.0" in notice


def test_tier_two_only_runs_when_the_unit_has_no_socket_so_the_tiers_never_both_speak():
    """Tier 1 (turn.py) speaks only on a turn the body is running, so the unit's socket to the body
    is open. Tier 2 is called from ShowCantReachHome, which patch 075 reaches only after
    OpenAudioChannel failed or found the channel closed."""
    offline = (FIRMWARE / "patches/075-offline-mode.patch").read_text()
    calls = [m.start() for m in re.finditer(r"ShowCantReachHome\(\);", offline)]
    assert calls
    for at in calls:
        before = offline[max(0, at - 400) : at]
        assert "OpenAudioChannel" in before or "IsAudioChannelOpened" in before
    assert (
        "maipai_sounds_wake_offline();"
        in (FIRMWARE / "patches/118-offline-phrases.patch").read_text()
    )
    turn = (HERE.parent / "maipai_body/bodies/stackchan/turn.py").read_text()
    assert "def _offline_line" in turn  # tier 1 is still there and unchanged in kind


# ---- the unit's event sounds are off during a music session and 30 s after (owner 2026-11-14)


def test_event_sounds_are_off_for_a_music_session_and_thirty_seconds_after():
    service, unit, clock, *_ = make()
    session = {"on": False}
    service.dance_active = lambda: session["on"]
    assert service.policy()["enabled"] is True
    session["on"] = True
    assert service.policy()["enabled"] is False  # the session runs: the unit is told to stay quiet
    clock.now += 600
    assert service.policy()["enabled"] is False
    session["on"] = False  # the session ends
    assert service.policy()["enabled"] is False
    clock.now += 29
    assert service.policy()["enabled"] is False
    clock.now += 2  # more than 30 s after: the sounds return by themselves
    assert service.policy()["enabled"] is True


def test_the_policy_is_pushed_when_the_session_state_changes_and_retried_quickly():
    service, unit, clock, *_ = make()
    session = {"on": False}
    service.dance_active = lambda: session["on"]
    assert service.push_policy()
    session["on"] = True
    assert service.push_policy()
    pushes = [a for n, a in unit.calls if n == "self.audio.set_sound_policy"]
    assert [p["enabled"] for p in pushes] == [True, False]
    unit.error = RuntimeError("No StackChan is connected")
    session["on"] = False
    service.policy()  # the tick that sees the session end
    clock.now += 31
    assert service.push_policy() is False
    unit.error = None
    clock.now += 3
    assert service.push_policy() is False  # inside the 5 s retry wait
    clock.now += 3
    assert service.push_policy() is True


# ---- the unit is told every sound is muted until the beeping source is named ----


def test_the_unit_is_silenced_by_default_whatever_the_settings(monkeypatch):
    monkeypatch.setattr(sounds_module, "SILENCE_UNIT_SOUNDS", True)
    service, unit, clock, _, _ = make()
    service.apply_settings({SOUNDS_ENABLED_KEY: True, MUTED_KEY: False, QUIET_KEY: False})
    assert service.push_policy(force=True)
    name, arguments = unit.calls[-1]
    assert name == "self.audio.set_sound_policy"
    assert arguments["enabled"] is False
    assert arguments["muted"] is True


def test_the_silenced_policy_is_repeated_every_thirty_seconds_and_first_on_connect(monkeypatch):
    monkeypatch.setattr(sounds_module, "SILENCE_UNIT_SOUNDS", True)
    service, unit, clock, _, _ = make()
    service.on_connect()
    assert unit.calls[0][0] == "self.audio.set_sound_policy"
    pushes = len([c for c in unit.calls if c[0] == "self.audio.set_sound_policy"])
    service.push_policy()
    assert len([c for c in unit.calls if c[0] == "self.audio.set_sound_policy"]) == pushes
    clock.now += sounds_module.SILENCED_POLICY_EVERY_S + 1
    service.push_policy()
    assert len([c for c in unit.calls if c[0] == "self.audio.set_sound_policy"]) == pushes + 1


def test_the_unit_counters_are_logged_with_their_change_once_a_minute(caplog):
    service, unit, clock, _, _ = make()
    unit.answer = '{"played":3,"refused":1,"clips_played":0,"clips_missing":0}'
    with caplog.at_level("INFO"):
        service.tick()
        clock.now += sounds_module.INFO_POLL_S + 1
        unit.answer = '{"played":5,"refused":1,"clips_played":0,"clips_missing":0}'
        service.tick()
    lines = [r.getMessage() for r in caplog.records if "robot activity" in r.getMessage()]
    assert any("unit sound counters played=3" in line for line in lines)
    assert any("since the last look played=+2" in line for line in lines)
