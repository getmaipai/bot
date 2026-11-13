"""The StackChan little dance (docs/dev/stackchan-little-dance-2026-11-13.md).

Everything runs against a fake clock and a recording fake robot: nothing here ran on a unit.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest

from maipai_body.bodies.stackchan import dance as D
from maipai_body.bodies.stackchan.dance import (
    DanceHooks,
    DanceRunner,
    DanceSettings,
    DanceSituation,
    is_dance_request,
    ring_frame,
)
from maipai_body.bodies.stackchan.dance_wiring import wire_dance
from maipai_body.bodies.stackchan.head_commands import (
    CAN_DO,
    HeadCommander,
    parse_head_command,
)
from maipai_body.bodies.stackchan.light_service import StackChanLightService
from maipai_body.bodies.stackchan.ring import RING_RGB
from maipai_body.bodies.stackchan.ring_indicator import StackChanRingIndicator
from maipai_body.hal.seam import Palette


@dataclass
class Ev:
    kind: str
    at_ms: int = 0
    extra: dict | None = None


def tap(ms: int) -> Ev:
    return Ev("head_touch", ms, {"tap": 1})


class World:
    """A fake clock, a fake robot and a scripted situation."""

    def __init__(self, **situation) -> None:
        self.t = 1000.0
        self.sit = DanceSituation(battery_percent=80, charging=False, **situation)
        self.log: list[tuple[float, str, object]] = []
        self.scheduled: list[tuple[float, object]] = []
        self.runner: DanceRunner
        self.settings = DanceSettings()
        self.start = 0.0

    def clock(self) -> float:
        return self.t

    def wait(self, seconds: float) -> bool:
        self.t += seconds
        for item in list(self.scheduled):
            if item[0] <= self.t:
                self.scheduled.remove(item)
                item[1]()
        return self.runner._stop.is_set()

    def at(self, seconds: float, fn) -> None:
        """Run ``fn`` once ``seconds`` have passed since the dance began."""
        self.scheduled.append((self.start + seconds, fn))

    def set(self, **changes) -> None:
        self.sit = replace(self.sit, **changes)

    def rec(self, name):
        return lambda *args: self.log.append((round(self.t - self.start, 2), name, args))

    def build(self, wake=None) -> DanceRunner:
        hooks = DanceHooks(
            start_dance=self.rec("dance"),
            stop_dance=self.rec("stop_dance"),
            show_face=self.rec("face"),
            write_ring=self.rec("ring"),
            take_ring=self.rec("take_ring"),
            give_ring_back=self.rec("give_ring_back"),
            level_head=self.rec("level"),
            situation=lambda: self.sit,
            wake=wake,
            hold=self.rec("hold"),
        )
        self.runner = DanceRunner(
            hooks, self.settings, clock=self.clock, wait=self.wait, spawn=lambda f: f()
        )
        self.start = self.t
        return self.runner

    def names(self, name: str) -> list[tuple[float, tuple]]:
        return [(t, a) for t, n, a in self.log if n == name]


def run(world: World, trigger: str = "hub"):
    runner = world.build() if not hasattr(world, "runner") else world.runner
    world.start = world.t
    return runner.request(trigger)


# ------------------------------------------------------------------ the ask in words


@pytest.mark.parametrize(
    "text",
    [
        "dance",
        "do a dance",
        "can you dance",
        "dance for me",
        "show me a dance",
        "do a little dance",
        "let's dance",
        "please dance",
        "could you do a dance for me",
        "dance a little",
        "give me a quick dance",
    ],
)
def test_spoken_dance_variants_are_a_dance_command(text):
    command = parse_head_command(text)
    assert command is not None and command.kind == "dance", text


@pytest.mark.parametrize(
    "text",
    [
        "what is a dance",
        "tell me about the dance",
        "I want to dance with you at the party tomorrow",
        "when is the school dance",
        "dance floor",
        "how do I dance the waltz",
    ],
)
def test_talk_about_dancing_still_goes_to_the_hub(text):
    command = parse_head_command(text)
    assert command is None or command.kind != "dance", text


def test_dance_is_no_longer_refused_as_unsupported():
    assert parse_head_command("dance").kind == "dance"
    assert parse_head_command("jump").kind == "cannot"
    assert is_dance_request("dance")
    assert not is_dance_request("dancer")


def test_head_commander_hands_a_dance_to_the_runner_before_any_head_gate():
    moves: list = []
    commander = HeadCommander(
        lambda *a: moves.append(a), blocked=lambda: "the emergency stop is latched"
    )
    command = parse_head_command("do a dance")
    assert commander.run(command) == CAN_DO  # no runner wired
    commander.dance = lambda: D.LINE_START
    assert commander.run(command) == D.LINE_START
    assert moves == []  # the commander never moves the head for a dance


# ------------------------------------------------------------------ the ring palette


def _dist(a, b):
    return max(abs(x - y) for x, y in zip(a, b, strict=True))


def test_show_colours_are_outside_every_status_colour_and_never_red():
    for colour in D.SHOW_COLOURS[:3]:  # gold, lime, mint (the sparkle is a warm white)
        for status in RING_RGB.values():
            assert _dist(colour, status) > 0.25, (colour, status)
    for colour in D.SHOW_COLOURS:
        assert not (colour[0] > 0 and colour[1] == 0 and colour[2] == 0)
    # the status meanings the show must never imitate: green, pink, violet, amber, cyan, blue
    for status in (Palette.GREEN, Palette.PINK, Palette.MAGENTA, Palette.AMBER, Palette.CYAN):
        for colour in D.SHOW_COLOURS:
            assert colour != RING_RGB[status]


def test_every_frame_has_two_colours_moves_and_stays_at_half_brightness():
    previous = None
    full_scale = round(168 * D.RING_BRIGHTNESS)
    for tick in range(60):
        for phase in (0, 1, 2):
            frame = ring_frame(tick, phase)
            assert len(frame) == 12
            lit = {p for p in frame if p != (0, 0, 0)}
            assert len(lit) >= 2, (tick, phase)
            assert max(max(p) for p in frame) <= full_scale
        frame = ring_frame(tick, tick % 3)
        assert frame != previous
        previous = frame
    for phase in (0, 1, 2):
        assert all(ring_frame(t, phase) != ring_frame(t + 1, phase) for t in range(40))


# ------------------------------------------------------------------ the sequence


def test_the_sequence_timing_faces_and_ring():
    world = World()
    reply = run(world)
    assert reply.started and reply.line == D.LINE_START
    assert [a[0] for _, a in world.names("dance")] == ["happy", "robot", "happy"]
    starts = [t for t, _ in world.names("dance")]
    assert starts[0] == 0.0
    assert starts[1] == pytest.approx(D.HAPPY_S + D.GAP_S, abs=D.TICK_S)
    assert starts[2] == pytest.approx(D.TOTAL_S - D.HAPPY_S, abs=D.TICK_S)
    assert 11.0 <= D.TOTAL_S <= 12.0
    faces = [a[0] for _, a in world.names("face")]
    assert faces == ["happy", "wink", "surprised", "happy", "neutral"]
    # the host never moves the head during the dance: only the firmware scripts and one final level
    assert len(world.names("level")) == 1
    assert world.log[-1][1] == "hold" or world.names("level")[0][0] >= D.TOTAL_S
    ring = world.names("ring")
    assert 40 <= len(ring) <= 50  # about four frames a second
    assert world.names("take_ring") and world.names("give_ring_back")
    assert world.names("stop_dance")
    assert world.runner.last_end_reason == "done"
    assert not world.runner.running


def test_the_ring_is_taken_before_the_first_frame_and_given_back_after_the_last():
    world = World()
    run(world)
    order = [n for _, n, _ in world.log if n in ("take_ring", "ring", "give_ring_back")]
    assert order[0] == "take_ring" and order[-1] == "give_ring_back"
    assert order.count("take_ring") == 1 and order.count("give_ring_back") == 1


# ------------------------------------------------------------------ triggers


def test_hub_command_starts_a_dance_and_a_second_one_is_refused_while_running():
    world = World()
    runner = world.build()
    world.at(2.0, lambda: results.append(runner.request("hub")))
    results: list = []
    first = runner.request("hub")
    assert first.started
    assert results and not results[0].started and "already running" in results[0].why


def test_voice_ask_waits_for_its_own_turn_to_end():
    world = World(in_turn=True)
    runner = world.build()
    world.at(1.0, lambda: world.set(in_turn=False))
    reply = runner.request("voice")
    assert reply.started and reply.line == D.LINE_START
    first_dance = world.names("dance")[0][0]
    assert 1.0 <= first_dance <= 1.5  # started right after the turn ended
    assert world.runner.last_end_reason == "done"


def test_voice_ask_gives_up_when_the_turn_never_ends():
    world = World(in_turn=True)
    runner = world.build()
    runner.request("voice")
    assert world.names("dance") == []
    assert runner.last_end_reason == "turn"
    assert world.names("give_ring_back") == [] and world.names("level") == []


def test_hub_never_starts_during_a_turn():
    world = World(in_turn=True)
    reply = world.build().request("hub")
    assert not reply.started and reply.line == D.LINE_NOT_NOW
    assert world.log == []


def test_taps_are_not_a_dance_trigger():
    with pytest.raises(ValueError):
        World().build().request("taps")


def test_hub_command_wakes_a_sleeping_unit_then_dances():
    world = World(awake=False)
    woke: list = []

    def wake():
        woke.append(world.t)
        world.set(awake=True)

    runner = world.build(wake=wake)
    reply = runner.request("hub")
    assert reply.started and woke
    assert [a[0] for _, a in world.names("dance")][0] == "happy"


@pytest.mark.parametrize("trigger", ["voice"])
def test_voice_does_not_wake_a_sleeper(trigger):
    world = World(awake=False)
    reply = world.build(wake=lambda: None).request(trigger)
    assert not reply.started and "asleep" in reply.why


def test_hub_command_on_a_unit_that_cannot_wake_is_refused():
    world = World(awake=False)
    assert not world.build().request("hub").started


# ------------------------------------------------------------------ gates


def _refused(world: World, trigger="voice"):
    reply = world.build().request(trigger)
    assert not reply.started
    assert world.names("dance") == [] and world.names("ring") == []
    return reply


def test_gate_setting_off():
    world = World()
    world.settings.enabled = False
    assert _refused(world).line == D.LINE_OFF


def test_gate_emergency_stop_tilt_offline_cues():
    for change in (
        {"estop": True},
        {"upright": False},
        {"offline": True},
        {"connected": False},
        {"camera_cue": True},
        {"live_cue": True},
    ):
        _refused(World(**change))


def test_gate_muted_or_full_quiet_hook():
    world = World(full_quiet="muted")
    assert "muted" in _refused(world).why


def test_gate_battery_needs_more_than_twenty_percent_when_not_charging():
    for percent in (20, 5):
        world = World()
        world.set(battery_percent=percent)
        assert "battery" in _refused(world).why
    world = World()
    world.set(battery_percent=None, charging=None)
    assert "unknown" in _refused(world).why
    world = World()
    world.set(battery_percent=21)
    assert world.build().request("hub").started


def test_a_charging_unit_may_dance_at_any_battery():
    world = World()
    world.set(battery_percent=8, charging=True)
    assert world.build().request("hub").started


def test_an_asked_dance_at_night_is_head_and_face_only():
    world = World(night=True)
    reply = world.build().request("voice")
    assert reply.started and reply.line == ""  # no spoken line at night
    assert [a[0] for _, a in world.names("dance")] == ["happy", "robot", "happy"]
    assert [a[0] for _, a in world.names("face")][:2] == ["happy", "wink"]
    for name in ("ring", "take_ring"):
        assert world.names(name) == []


def test_one_minute_between_dances():
    world = World()
    runner = world.build()
    assert runner.request("hub").started
    reply = runner.request("hub")
    assert not reply.started and "under a minute" in reply.why
    world.t += D.MIN_GAP_S - 5
    assert not runner.request("hub").started
    world.t += 6
    assert runner.request("hub").started


def test_the_music_dance_rounds_are_not_held_to_the_one_minute():
    world = World()
    runner = world.build()
    runner._last_end = (
        world.t - 1.0
    )  # a round just ended (the music controller spaces its own rounds)
    assert runner.request("auto").started
    other = World()
    held = other.build()
    held._last_end = other.t - 1.0
    assert not held.request("hub").started  # a spoken or hub ask still waits the minute


def test_a_dance_that_never_started_does_not_cost_the_minute():
    world = World(in_turn=True)
    runner = world.build()
    runner.request("voice")  # the turn never ended
    world.set(in_turn=False)
    assert runner.request("hub").started


# ------------------------------------------------------------------ early ends


def _interrupted(change, expect, at=3.0, world=None):
    """Start a dance, apply ``change(world)`` at ``at`` seconds, check it ended at once."""
    world = world or World()
    runner = world.build()
    world.at(at, lambda: change(world))
    reply = runner.request("hub")
    assert reply.started
    assert runner.last_end_reason == expect, runner.last_end_reason
    assert not runner.running
    # ended at once: no later script step ran and the unit's own dance was stopped
    assert world.log and max(t for t, *_ in world.log) <= at + 2 * D.TICK_S
    assert world.names("stop_dance")
    assert world.names("give_ring_back")  # the ring is dark and the normal rules repaint it
    return world


def test_ends_on_a_turn_or_wake_word_without_touching_the_head_or_face():
    world = _interrupted(lambda w: w.set(in_turn=True), "turn")
    assert world.names("level") == []
    assert [a[0] for _, a in world.names("face")] == ["happy"]  # no neutral over the turn's face


def test_ends_on_a_touch():
    world = World()
    runner = world.build()
    world.at(3.0, lambda: runner.on_events([Ev("head_touch", 0, {"tap": 1})], world.t))
    runner.request("hub")
    assert runner.last_end_reason == "touch"
    assert max(t for t, *_ in world.log) <= 3.0 + 2 * D.TICK_S
    assert world.names("stop_dance") and world.names("give_ring_back")


def test_ends_on_a_swipe_or_a_shake():
    for event, reason in (
        (Ev("head_swipe_forward", 0), "touch"),
        (Ev("shake", 0), "shake"),
    ):
        world = World()
        runner = world.build()
        world.at(3.0, lambda e=event, r=runner, w=world: r.on_events([e], w.t))
        runner.request("hub")
        assert runner.last_end_reason == reason
        assert world.names("level") == [] or reason == "touch"


def test_the_starts_own_motion_is_ignored_for_the_first_second():
    world = World()
    runner = world.build()
    world.at(0.3, lambda: runner.on_events([Ev("shake", 0)], world.t))
    runner.request("hub")
    assert runner.last_end_reason == "done"


def test_ends_on_a_tilt_without_moving_the_head():
    world = _interrupted(lambda w: w.set(upright=False), "tilt")
    assert world.names("level") == []


def test_ends_on_a_camera_picture_and_on_the_live_cue():
    _interrupted(lambda w: w.set(camera_cue=True), "picture")
    world = _interrupted(lambda w: w.set(live_cue=True), "turn")
    assert world.names("ring")  # frames were shown before the cue


def test_the_ring_never_draws_over_a_privacy_cue():
    world = World()
    runner = world.build()
    world.at(3.0, lambda: world.set(camera_cue=True))
    runner.request("hub")
    cue_time = 3.0
    assert not [t for t, *_ in world.names("ring") if t > cue_time + D.TICK_S]


def test_ends_on_low_battery():
    _interrupted(lambda w: w.set(battery_low=True), "battery")
    world = World()
    runner = world.build()
    world.at(3.0, lambda: world.set(battery_percent=19))
    runner.request("hub")
    assert runner.last_end_reason == "battery"
    world = World()
    runner = world.build()
    world.at(3.0, lambda: world.set(battery_percent=5, charging=True))  # plugged in: fine
    runner.request("hub")
    assert runner.last_end_reason == "done"


def test_ends_when_the_unit_goes_offline_or_the_stop_latches_or_it_falls_asleep():
    _interrupted(lambda w: w.set(offline=True), "offline")
    _interrupted(lambda w: w.set(connected=False), "offline")
    world = _interrupted(lambda w: w.set(estop=True), "estop")
    assert world.names("level") == []
    _interrupted(lambda w: w.set(awake=False), "asleep")


def test_ends_when_it_goes_quiet_or_the_setting_is_turned_off():
    _interrupted(lambda w: w.set(full_quiet="muted"), "quiet")
    _interrupted(lambda w: setattr(w.settings, "enabled", False), "settings")


def test_a_normal_end_restores_the_face_and_levels_the_head_once():
    world = World()
    run(world)
    assert world.names("face")[-1][1] == ("neutral",)
    assert len(world.names("level")) == 1


def test_a_failing_robot_call_ends_the_dance_cleanly():
    world = World()
    runner = world.build()

    def boom(_name):
        raise RuntimeError("link down")

    runner._hooks.start_dance = boom
    runner.request("hub")
    assert runner.last_end_reason == "error"
    assert not runner.running
    assert len(world.names("give_ring_back")) == 1  # the ring it took is given back
    assert world.names("hold")[-1][1] == (False,)
    # an error before anything visible does not cost the next dance its minute
    runner._hooks.start_dance = world.rec("dance")
    world.t += D.MIN_GAP_S + 1
    assert runner.request("hub").started


# ------------------------------------------------------------------ settings and the ring switch


def test_settings_frame_sets_both_keys_and_ignores_junk():
    settings = DanceSettings()
    assert settings.enabled and settings.show_ring
    settings.apply({"robot.dance.enabled": False, "robot.dance.show_ring": False})
    assert not settings.enabled and not settings.show_ring
    settings.apply({"robot.dance.enabled": "yes", "robot.dance.show_ring": 1})
    assert not settings.enabled and not settings.show_ring
    settings.apply({"robot.dance.enabled": True})
    assert settings.enabled and not settings.show_ring


def test_show_ring_off_dances_with_head_and_face_only():
    world = World()
    world.settings.show_ring = False
    reply = world.build().request("voice")
    assert reply.started and reply.line == D.LINE_START
    assert world.names("ring") == [] and world.names("take_ring") == []
    assert [a[0] for _, a in world.names("dance")] == ["happy", "robot", "happy"]


# ------------------------------------------------------------------ the light service


def test_the_light_service_stops_painting_while_the_ring_is_taken_and_repaints_after():
    writes: list = []
    indicator = StackChanRingIndicator(lambda rgb: writes.append(rgb))
    service = StackChanLightService(indicator, minute=lambda: 12 * 60)
    service.update(battery_low=True)  # a status look the dance must not leave behind
    shown = list(writes)
    assert shown and shown[-1] != (0, 0, 0)
    service.take_ring()
    service.update(offline=False)
    service.tick()
    assert writes == shown  # nothing painted while the show owns the ring
    service.give_ring_back()
    assert writes[-1] == shown[-1]  # the status look is written again, even though unchanged


def test_the_light_service_goes_dark_after_the_show_when_nothing_is_lit():
    writes: list = []
    service = StackChanLightService(
        StackChanRingIndicator(lambda rgb: writes.append(rgb)), minute=lambda: 12 * 60
    )
    service.refresh()
    service.take_ring()
    service.give_ring_back()
    assert writes[-1] == (0, 0, 0)


# ------------------------------------------------------------------ the live wiring, with fakes


class FakeClient:
    def __init__(self) -> None:
        self.calls: list = []
        self.battery = {"percent": 70, "charging": False}

    def get_battery_status(self):
        return self.battery

    def companion(self):
        return SimpleNamespace(
            dance=lambda name: self.calls.append(("dance", name)),
            stop_dance=lambda: self.calls.append(("stop_dance",)),
        )


def _wired(*, night=False, awake=True):
    client = FakeClient()
    leds: list = []
    robot = SimpleNamespace(
        estop_engaged=False,
        leds=SimpleNamespace(many=lambda updates: leds.append(updates)),
    )
    voice = SimpleNamespace(robot=SimpleNamespace(client=client, robot=robot))
    faces: list = []
    holds = {"moves": 0}
    behavior = SimpleNamespace(
        _rest=SimpleNamespace(stage="awake" if awake else "asleep"),
        privacy=SimpleNamespace(muted=False),
        _active=SimpleNamespace(is_set=lambda: False),
        pose_held=lambda: False,
        show_face=lambda expression: faces.append(expression),
        _note_own_move=lambda: holds.__setitem__("moves", holds["moves"] + 1),
        rest_step=lambda now: setattr(behavior._rest, "stage", "awake"),
        _last_person_seen=0.0,
        dance_settings=DanceSettings(),
    )
    light_writes: list = []
    light = StackChanLightService(
        StackChanRingIndicator(lambda rgb: light_writes.append(rgb)), minute=lambda: 12 * 60
    )
    commander = HeadCommander(lambda *a: None)
    level: list = []
    runner = wire_dance(
        voice=voice,
        behavior=behavior,
        light=light,
        night=SimpleNamespace(night=night),
        head_commander=commander,
        level_head=lambda: level.append(1),
        device_connected=lambda: True,
    )
    # run the dance inline on a fake clock
    clock = {"t": 5000.0}
    runner._clock = lambda: clock["t"]

    def wait(seconds):
        clock["t"] += seconds
        return runner._stop.is_set()

    runner._wait = wait
    runner._spawn = lambda f: f()
    return SimpleNamespace(
        runner=runner,
        behavior=behavior,
        commander=commander,
        client=client,
        leds=leds,
        faces=faces,
        level=level,
        light=light,
        clock=clock,
        robot=robot,
        light_writes=light_writes,
    )


def test_wiring_the_spoken_ask_runs_the_firmware_dances_and_the_ring_through_the_adapter():
    w = _wired()
    line = w.commander.run(parse_head_command("can you dance"))
    assert line == D.LINE_START
    assert [c[1] for c in w.client.calls if c[0] == "dance"] == ["happy", "robot", "happy"]
    assert ("stop_dance",) in w.client.calls
    assert len(w.leds) >= 40 and all(len(frame) == 12 for frame in w.leds)
    assert w.faces[-1] == "neutral" and w.level == [1]
    assert not w.behavior.dance_active()
    assert w.light_writes[-1] == (0, 0, 0)  # the ring is dark again


def test_wiring_the_hub_command_starts_a_dance_and_answers():
    w = _wired()
    answer = w.behavior.dance_command({})
    assert answer == {"dance": "started", "why": ""}
    again = w.behavior.dance_command({})
    assert again["dance"] == "refused"


def test_wiring_the_hub_command_wakes_a_sleeping_unit():
    w = _wired(awake=False)
    assert w.behavior.dance_command({})["dance"] == "started"
    assert w.behavior._rest.stage == "awake"


def test_wiring_taps_on_the_head_never_start_a_dance():
    w = _wired()
    w.behavior.dance_events([tap(100_000), tap(100_400), tap(100_900)], w.clock["t"])
    assert not w.client.calls


def test_wiring_ordinary_petting_never_starts_a_dance():
    w = _wired()
    petting = [Ev("head_touch", ms, {"strong": 1}) for ms in range(0, 3000, 300)]
    petting += [Ev("head_swipe_forward", 1500), Ev("head_swipe_back", 1700)]
    w.behavior.dance_events(petting, w.clock["t"])
    assert not w.client.calls


def test_wiring_an_asked_dance_at_night_has_no_ring():
    w = _wired(night=True)
    assert w.commander.run(parse_head_command("dance")) == ""
    assert [c[1] for c in w.client.calls if c[0] == "dance"] == ["happy", "robot", "happy"]
    assert w.leds == []


def test_wiring_a_failed_battery_read_refuses_the_dance():
    w = _wired()

    def broken():
        raise RuntimeError("no answer")

    w.client.get_battery_status = broken
    assert w.commander.run(parse_head_command("dance")) == D.LINE_NOT_NOW
    assert not w.client.calls


def test_wiring_the_ambient_flag_is_set_while_a_dance_runs():
    w = _wired()
    seen: list = []
    w.runner._hooks.start_dance = lambda name: seen.append(w.behavior.dance_active())
    w.commander.run(parse_head_command("dance"))
    assert seen and all(seen)
