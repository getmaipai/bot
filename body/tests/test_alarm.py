"""ALARM-PLAY-01: the safety alarm controller (no model, no turn, no TTS)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from maipai_body.initiative import alarm as alarm_module
from maipai_body.initiative.alarm import (
    BACKSTOP_FACTOR,
    VOLUME_FLOOR,
    AlarmController,
    chime_samples,
    clamp_repeat,
)
from maipai_body.speaker_evidence import speaker_evidence

ANNA = "person-anna01"
KID = "person-kid003"


class _Player:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def chime(self) -> None:
        self.events.append(("chime",))

    def clips(self, ids) -> bool:
        self.events.append(("clips", tuple(ids)))
        return True

    def stop(self) -> None:
        self.events.append(("stop",))


class _Volume:
    def __init__(self, level: int) -> None:
        self.level = level
        self.history: list[int] = []

    def get_level(self) -> int:
        return self.level

    def set_level(self, level: int) -> None:
        self.level = level
        self.history.append(level)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _controller(*, audience=(), volume=None, volume_setting=VOLUME_FLOOR, send_ok=True, **kw):
    player = _Player()
    sent: list[dict] = []
    shown: list[bool] = []
    clock = _Clock()

    def send(message):
        sent.append(message)
        return send_ok

    controller = AlarmController(
        player=player,
        present=shown.append,
        resolve_clips=lambda kind, area: [f"alarm-{kind}-x"] if area else ["alarm-generic"],
        child_clips=lambda: ["alarm-child"],
        send_action=send,
        audience=lambda: list(audience),
        is_child=lambda entry: entry["person"] in (None, KID),
        evidence=lambda: speaker_evidence(ANNA, "voice", "confirmed"),
        volume=volume,
        clock=clock,
        volume_setting=volume_setting,
        **kw,
    )
    return controller, player, sent, shown, clock


def _active(alarm_id="a1", area="kitchen", kind="smoke"):
    return {"alarm_id": alarm_id, "area": area, "kind": kind, "state": "active"}


def test_an_active_alarm_chimes_then_says_the_area_line_and_holds_the_pose():
    controller, player, _sent, shown, _clock = _controller()
    controller.handle_command(_active())
    assert player.events == [("chime",), ("clips", ("alarm-smoke-x",))]
    assert shown == [True]
    assert controller.active


def test_the_generic_line_plays_when_there_is_no_area_line():
    controller, player, *_ = _controller()
    controller.handle_command(_active(area=None))
    assert ("clips", ("alarm-generic",)) in player.events


def test_the_volume_is_raised_to_the_floor_and_restored():
    volume = _Volume(10)
    controller, *_ = _controller(volume=volume, volume_setting=20)
    controller.handle_command(_active())
    assert volume.level == VOLUME_FLOOR  # a setting below the floor is lifted to it
    controller.handle_command({"alarm_id": "a1", "state": "cleared"})
    assert volume.level == 10


def test_the_alarm_volume_setting_above_the_floor_is_used():
    controller, *_ = _controller(volume_setting=90)
    assert controller.alarm_volume() == 90
    controller.apply_settings({"safety.alarm.volume": 5})
    assert controller.alarm_volume() == VOLUME_FLOOR


def test_a_child_or_unknown_person_present_gets_the_child_line_too():
    child = {"person": KID, "basis": "face", "level": "confirmed"}
    controller, player, *_ = _controller(audience=[child])
    controller.handle_command(_active())
    assert ("clips", ("alarm-child",)) in player.events
    unknown = {"person": None, "basis": "face", "level": "unknown"}
    controller, player, *_ = _controller(audience=[unknown])
    controller.handle_command(_active())
    assert ("clips", ("alarm-child",)) in player.events


def test_adults_alone_get_no_child_line():
    adult = {"person": ANNA, "basis": "face", "level": "confirmed"}
    controller, player, *_ = _controller(audience=[adult])
    controller.handle_command(_active())
    assert ("clips", ("alarm-child",)) not in player.events


def test_every_active_command_repeats_the_alarm():
    controller, player, _sent, shown, _clock = _controller()
    controller.handle_command(_active())
    controller.handle_command(_active())
    assert [e for e in player.events if e[0] == "chime"] == [("chime",), ("chime",)]
    assert shown == [True]  # the pose is entered once


def test_stop_sends_one_acknowledgement_with_evidence_and_does_not_silence():
    controller, player, sent, shown, clock = _controller()
    controller.handle_command(_active())
    assert controller.on_spoken("stop") is True
    assert controller.on_spoken("stop") is False  # one per alarm
    assert sent == [
        {
            "type": "alarm_action",
            "alarm_id": "a1",
            "action": "acknowledge",
            "speaker_evidence": speaker_evidence(ANNA, "voice", "confirmed"),
        }
    ]
    assert controller.active and shown == [True]
    assert ("stop",) not in player.events
    # the hub still says active, so it still repeats
    controller.handle_command(_active())
    assert [e for e in player.events if e[0] == "chime"] == [("chime",), ("chime",)]


def test_a_stop_while_the_channel_is_down_may_be_retried():
    controller, *_ = _controller(send_ok=False)
    controller.handle_command(_active())
    assert controller.on_spoken("stop") is False
    assert controller.on_spoken("stop") is False  # tried again, not swallowed


def test_i_know_also_acknowledges_and_other_words_do_not():
    controller, _player, sent, *_ = _controller()
    controller.handle_command(_active())
    assert controller.on_spoken("hello") is False
    assert controller.on_spoken("I know") is True
    assert len(sent) == 1


def test_no_acknowledgement_without_a_live_alarm():
    controller, _player, sent, *_ = _controller()
    assert controller.on_spoken("stop") is False
    assert sent == []


@pytest.mark.parametrize("state", ["cleared", "false_alarm"])
def test_the_hubs_next_state_ends_it(state):
    controller, player, _sent, shown, _clock = _controller()
    controller.handle_command(_active())
    controller.handle_command({"alarm_id": "a1", "state": state})
    assert not controller.active
    assert ("stop",) in player.events
    assert shown == [True, False]


def test_a_clear_for_another_alarm_is_ignored():
    controller, *_ = _controller()
    controller.handle_command(_active())
    controller.handle_command({"alarm_id": "other", "state": "cleared"})
    assert controller.active


def test_an_unknown_state_or_missing_id_is_refused():
    controller, *_ = _controller()
    with pytest.raises(ValueError):
        controller.handle_command({"alarm_id": "a1", "state": "paused"})
    with pytest.raises(ValueError):
        controller.handle_command({"state": "active"})


def test_the_local_backstop_replays_when_the_hub_repeat_is_late():
    controller, player, _sent, _shown, clock = _controller(repeat_seconds=20)
    controller.handle_command(_active())
    controller.tick()
    assert len(player.events) == 2  # too soon
    clock.now += 20 * BACKSTOP_FACTOR + 1
    controller.tick()
    assert [e for e in player.events if e[0] == "chime"] == [("chime",), ("chime",)]


def test_the_backstop_does_nothing_without_an_alarm():
    controller, player, _sent, _shown, clock = _controller()
    clock.now += 1000
    controller.tick()
    assert player.events == []


def test_repeat_seconds_are_clamped_and_follow_settings():
    assert clamp_repeat(1) == 10
    assert clamp_repeat(500) == 60
    assert clamp_repeat("x") == 20
    controller, *_ = _controller()
    controller.apply_settings({"safety.alarm.repeat_seconds": 30})
    assert controller._repeat_s == 30


def test_a_failing_player_never_raises_into_the_channel():
    controller, player, *_ = _controller()

    def boom():
        raise RuntimeError("speaker gone")

    player.chime = boom
    controller.handle_command(_active())
    assert controller.active


def test_the_chime_is_a_plain_tone_burst():
    samples = chime_samples(16000)
    assert samples.dtype.name == "float32" and 0.4 < len(samples) / 16000 < 0.7
    assert float(abs(samples).max()) <= 1.0


def test_the_module_imports_no_speech_turn_or_model_client():
    tree = ast.parse(Path(alarm_module.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    banned = ("speech", "turn", "tts", "stt", "openai", "anthropic", "llm", "sherpa", "requests")
    offenders = {m for m in imported if any(b in m.lower().split(".") for b in banned)}
    assert not offenders, offenders
    assert not any("tts_playback" in m or "turn_client" in m for m in imported)
