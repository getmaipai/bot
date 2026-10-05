"""LINK-STATE-01 rung 1: a closed list of fixed local commands with fixed replies."""

from __future__ import annotations

import datetime

import pytest

from maipai_body.link.commands import (
    COMMAND_PHRASES,
    CommandRouter,
    LocalCommand,
    LocalTimers,
    missing_clip_ids,
    route_phrase,
)
from maipai_body.link.state_machine import LinkPhase, LinkStateMachine
from maipai_body.speech.offline_clips import load_manifest
from tests.ladder_fakes import FakeClock

UTC = datetime.UTC


class _Volume:
    def __init__(self, level: int = 50) -> None:
        self.level = level

    def get_level(self) -> int:
        return self.level

    def set_level(self, level: int) -> None:
        self.level = level


def _router(clock: FakeClock | None = None, volume: _Volume | None = None):
    clock = clock or FakeClock()
    machine = LinkStateMachine(clock=clock, wall_clock=clock.wall_clock)
    volume = volume or _Volume()
    timers = LocalTimers(clock)
    router = CommandRouter(
        volume=volume,
        timers=timers,
        machine=machine,
        wall_clock=clock.wall_clock,
        tz=UTC,
        timer_s=300.0,
    )
    return router, machine, volume, timers, clock


def test_the_closed_list_is_exactly_the_six_commands():
    assert set(COMMAND_PHRASES) == {
        LocalCommand.STOP,
        LocalCommand.QUIETER,
        LocalCommand.LOUDER,
        LocalCommand.TIMER,
        LocalCommand.TIME,
        LocalCommand.CONNECTED,
    }


@pytest.mark.parametrize(
    ("heard", "command"),
    [
        ("stop", LocalCommand.STOP),
        ("Stop.", LocalCommand.STOP),
        ("quieter", LocalCommand.QUIETER),
        ("louder!", LocalCommand.LOUDER),
        ("timer", LocalCommand.TIMER),
        ("what time is it", LocalCommand.TIME),
        ("What time is it?", LocalCommand.TIME),
        ("are you connected", LocalCommand.CONNECTED),
        ("Are you connected?", LocalCommand.CONNECTED),
    ],
)
def test_each_phrase_routes_to_its_command(heard, command):
    assert route_phrase(heard) is command


@pytest.mark.parametrize(
    "heard",
    ["", "   ", "what's the weather", "stop the music please", "tell me a joke", "timer for ten"],
)
def test_nothing_outside_the_list_routes(heard):
    assert route_phrase(heard) is None


def test_stop_has_a_fixed_reply_and_no_speech_of_its_own():
    router, *_ = _router()
    reply = router.handle(LocalCommand.STOP)
    assert reply.text == "Stopped."
    assert reply.clip_ids == ("cmd.stopped",)


def test_quieter_and_louder_step_the_volume_and_stay_in_range():
    router, _, volume, *_ = _router(volume=_Volume(50))
    assert router.handle(LocalCommand.QUIETER).text == "Quieter."
    assert volume.level == 40
    assert router.handle(LocalCommand.LOUDER).text == "Louder."
    assert volume.level == 50
    volume.level = 3
    router.handle(LocalCommand.QUIETER)
    assert volume.level == 0
    volume.level = 98
    router.handle(LocalCommand.LOUDER)
    assert volume.level == 100


def test_the_timer_command_starts_a_fixed_local_timer_that_fires_once():
    router, _, _, timers, clock = _router()
    reply = router.handle(LocalCommand.TIMER)
    assert reply.text == "Timer set."
    assert reply.clip_ids == ("cmd.timer_set",)
    clock.advance(299.0)
    assert timers.pop_due() is False
    clock.advance(1.0)
    assert timers.pop_due() is True
    assert timers.pop_due() is False


def test_the_time_reply_reads_the_injected_wall_clock():
    router, *_ = _router()
    reply = router.handle(LocalCommand.TIME)
    assert reply.text == "It is 08:00."
    # spoken only as the prefix clip plus digit clips; none are rendered yet
    assert reply.clip_ids[0] == "cmd.time_prefix"
    assert reply.clip_ids[1:] == ("char.0", "char.8", "char.0", "char.0")


def test_are_you_connected_answers_from_the_machine_not_a_model():
    router, machine, *_ = _router()
    assert router.handle(LocalCommand.CONNECTED).text == "Connected to home."
    assert router.handle(LocalCommand.CONNECTED).clip_ids == ()
    machine.link_lost("unreachable: ConnectTimeout")
    reply = router.handle(LocalCommand.CONNECTED)
    assert reply.text.startswith("Can't reach home.")
    assert "unreachable: ConnectTimeout" in reply.text
    assert reply.clip_ids == ("line.unreachable",)
    assert machine.phase is LinkPhase.RECONNECTING


def test_the_clip_ids_the_replies_need_but_the_bundle_lacks_are_listed():
    # G4b owns the clip set. This documents exactly what rung 1 asks it to add.
    assert missing_clip_ids(load_manifest()) == {
        "cmd.stopped",
        "cmd.quieter",
        "cmd.louder",
        "cmd.timer_set",
        "cmd.timer_done",
        "cmd.time_prefix",
        "char.0",
        "char.1",
    }


def test_the_speaker_can_say_only_rendered_clips_that_exist(tmp_path):
    from dataclasses import replace

    from maipai_body.speech.offline_clips import ClipBundle, OfflineSpeaker

    manifest = load_manifest()
    speaker = OfflineSpeaker(ClipBundle(tmp_path, manifest), playback=None)
    assert speaker.can_say(["line.reconnect"]) is False  # unrendered: no checksum
    assert speaker.can_say(["no.such.clip"]) is False

    stamped = replace(
        manifest,
        clips=tuple(
            replace(c, sha256="ab" * 32) if c.id == "line.reconnect" else c for c in manifest.clips
        ),
    )
    speaker = OfflineSpeaker(ClipBundle(tmp_path, stamped), playback=None)
    assert speaker.can_say(["line.reconnect"]) is False  # stamped but no file on disk
    (tmp_path / "line_reconnect.wav").write_bytes(b"x")
    assert speaker.can_say(["line.reconnect"]) is True
