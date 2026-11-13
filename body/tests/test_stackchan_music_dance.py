"""The StackChan music dance, host half (docs/dev/stackchan-music-dance-2026-11-13.md).

A fake clock and scripted one-second feature streams drive the decision layer and its stages; the
dance itself is the little dance's DanceRunner on its own fake clock. Nothing here ran on a unit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

import pytest

from maipai_body.bodies.stackchan import music_dance as M
from maipai_body.bodies.stackchan.dance import (
    DanceHooks,
    DanceRunner,
    DanceSettings,
    DanceSituation,
)
from maipai_body.bodies.stackchan.music_dance import (
    AUTO_PLAN,
    FAST,
    MusicDance,
    MusicDanceHooks,
    MusicFeat,
    judge,
    parse_music_feat,
)
from maipai_body.bodies.stackchan.ring import RING_RGB

MUSIC = M.TEST_FEAT  # 120 bpm, confidence 80
SPEECH = MusicFeat(lv=1500, b=(50, 40, 8, 2), bpm=110, tc=45, fl=15, zc=25, zs=250, mo=60, ps=45)
TALK_PAUSES = MusicFeat(
    lv=1500, b=(50, 40, 8, 2), bpm=90, tc=40, fl=12, zc=25, zs=250, mo=20, ps=55
)
NOISE = MusicFeat(lv=2000, b=(5, 14, 31, 50), bpm=144, tc=60, fl=97, zc=239, zs=4, mo=5, ps=0)
QUIET_MUSIC = replace(MUSIC, lv=300)
NO_BEAT = replace(MUSIC, bpm=0, tc=0)


@dataclass
class Ev:
    kind: str
    at_ms: int = 0
    extra: dict | None = None


class World:
    """A controller on a fake clock with recording hooks and a scripted situation."""

    def __init__(self, *, auto: bool = True, sensitivity: str = "medium", **situation) -> None:
        self.t = 5000.0
        self.sit = DanceSituation(battery_percent=90, charging=False, **situation)
        self.settings = DanceSettings()
        self.settings.auto = auto
        self.settings.auto_sensitivity = sensitivity
        self.calls: list[tuple[float, str, object]] = []
        self.dancing = False
        self.dance_refusal = ""
        self.faces = iter(["happy", "wink"] * 20)
        hooks = MusicDanceHooks(
            request_dance=self._request_dance,
            stop_dance=self._stop_dance,
            dance_running=lambda: self.dancing,
            nod=lambda face, cancelled: self.calls.append((self.t, "nod", face)),
            restore_face=lambda: self.calls.append((self.t, "restore_face", None)),
            situation=lambda: self.sit,
        )
        self.ctl = MusicDance(
            hooks, self.settings, spawn=lambda fn: fn(), choose_face=lambda: next(self.faces)
        )

    def _request_dance(self):
        self.calls.append((self.t, "request_dance", None))
        if self.dance_refusal:
            return False, self.dance_refusal
        self.dancing = True
        return True, ""

    def _stop_dance(self, why):
        self.calls.append((self.t, "stop_dance", why))
        self.dancing = False

    def names(self, name: str) -> list[float]:
        return [round(t - 5000.0, 2) for t, n, _ in self.calls if n == name]

    def second(self, feat: MusicFeat | None) -> None:
        """One second passes; the unit sends ``feat`` (None: nothing, a quiet room)."""
        self.t += 1.0
        if feat is not None:
            self.ctl.feed(feat, self.t)
        self.ctl.tick(self.t)

    def play(self, feat: MusicFeat | None, seconds: int) -> None:
        for _ in range(seconds):
            self.second(feat)

    def session(self, music_s: int = 25) -> None:
        """Music for ``music_s`` seconds; the dance ends on its own after a minute."""
        self.play(MUSIC, music_s)
        if self.dancing:
            self.play(MUSIC, 2)
            self.dancing = False  # the runner finished
        self.play(None, 16)  # quiet: the session ends and re-arms


# ------------------------------------------------------------------ the numbers from the unit


def test_parse_reads_the_unit_event_and_rejects_missing_fields():
    extra = {"lv": 2400, "b0": 40, "b1": 35, "b2": 18, "b3": 7, "bpm": 120, "tc": 80, "fl": 12}
    extra |= {"zc": 15, "zs": 80, "mo": 15, "ps": 3, "on": 70}
    feat = parse_music_feat(extra)
    assert feat == replace(MUSIC, on=70)
    assert parse_music_feat({}) is None
    assert parse_music_feat(None) is None
    assert parse_music_feat({**extra, "tc": "80"}) is None  # strings are not numbers
    assert parse_music_feat({**extra, "tc": True}) is None
    assert parse_music_feat({**extra, "muted": 1}).muted is True


@pytest.mark.parametrize("sensitivity", ["low", "medium", "high"])
def test_judge_music_versus_the_rest(sensitivity):
    assert judge(MUSIC, sensitivity).music
    assert not judge(SPEECH, sensitivity).music
    assert judge(replace(SPEECH, tc=90), sensitivity).why == "speech rhythm"
    assert judge(NOISE, sensitivity).why == "noise"
    assert judge(QUIET_MUSIC, sensitivity).why == "quiet"
    assert judge(NO_BEAT, sensitivity).why == "no steady beat"
    assert judge(replace(MUSIC, muted=True), sensitivity).why == "muted"
    assert judge(replace(MUSIC, bpm=40), sensitivity).why == "no steady beat"
    assert judge(replace(MUSIC, bpm=200), sensitivity).why == "no steady beat"


def test_pauses_with_a_loose_beat_are_speech_but_a_steady_sparse_beat_is_music():
    assert judge(TALK_PAUSES, "high").why == "pauses"
    assert judge(replace(MUSIC, ps=95, tc=90), "medium").music  # a click track


def test_sensitivity_moves_the_beat_bar():
    weak = replace(MUSIC, tc=30)
    assert not judge(weak, "low").music
    assert not judge(weak, "medium").music
    assert judge(weak, "high").music
    assert judge(replace(MUSIC, tc=40), "medium").music
    assert not judge(replace(MUSIC, tc=40), "low").music


def test_a_running_stage_judges_a_little_more_gently():
    dip = replace(MUSIC, tc=28)
    assert not judge(dip, "medium").music
    assert judge(dip, "medium", relaxed=True).music


# ------------------------------------------------------------------ detection and the nod


def test_it_does_nothing_while_the_setting_is_off(caplog):
    world = World(auto=False)
    with caplog.at_level(logging.INFO):
        world.play(MUSIC, 60)
    assert world.calls == []
    assert world.ctl.state == "idle"
    assert not [r for r in caplog.records if "music" in r.name]


def test_three_seconds_of_music_do_nothing_and_four_give_the_nod():
    world = World()
    world.play(MUSIC, 4)  # events at +1, +2, +3, +4: a 3 s run so far
    assert world.names("nod") == []
    assert world.ctl.state == "idle"
    world.second(MUSIC)  # the fifth second: 4.0 s of run
    assert world.names("nod") == [5.0]
    assert world.ctl.state == "nod"
    assert [a for _, n, a in world.calls if n == "nod"] == ["happy"]


def test_the_nod_face_alternates_between_happy_and_wink_by_the_hooks_choice():
    world = World()
    world.session()
    assert [a for _, n, a in world.calls if n == "nod"] == ["happy"]


def test_the_nod_ends_after_three_seconds_and_the_face_is_restored():
    world = World()
    world.play(MUSIC, 5)
    world.play(MUSIC, 3)
    assert world.ctl.state == "watch"
    assert world.names("restore_face")


def test_a_run_of_music_with_one_missed_second_still_counts():
    world = World()
    for feat in (MUSIC, MUSIC, MUSIC, None, MUSIC, MUSIC):
        world.second(feat)
    assert world.names("nod") == [5.0]


def test_a_gap_resets_the_count():
    world = World()
    world.play(MUSIC, 3)
    world.play(SPEECH, 3)
    world.play(MUSIC, 4)  # only a 3 s run again
    assert world.names("nod") == []
    world.second(MUSIC)
    assert world.names("nod") == [11.0]


def test_speech_like_streams_never_trigger_anything():
    world = World()
    for feat in (SPEECH, TALK_PAUSES, NOISE, QUIET_MUSIC, NO_BEAT):
        world.play(feat, 120)
    assert world.calls == []
    assert world.ctl.state == "idle"


def test_speech_alternating_with_a_music_like_second_never_reaches_four_seconds():
    world = World()
    for _ in range(60):
        world.second(MUSIC)
        world.second(SPEECH)
        world.second(SPEECH)
    assert world.calls == []


# ------------------------------------------------------------------ the build-up and the dance


def test_twenty_four_seconds_of_music_start_the_build_up_and_dance():
    world = World()
    world.play(MUSIC, 23)
    assert world.names("request_dance") == []
    world.second(MUSIC)  # 24 s: 20 s after the nod at +5... the nod was at second 5
    assert world.names("request_dance") == []
    world.play(MUSIC, 1)
    assert world.names("nod") == [5.0]
    assert world.names("request_dance") == [25.0]
    assert world.ctl.state == "show"


def test_the_music_stopping_before_the_build_up_ends_the_session():
    world = World()
    world.play(MUSIC, 10)
    world.play(None, 8)
    assert world.names("request_dance") == []
    assert world.ctl.state == "spent"


def test_the_dance_ends_on_five_seconds_of_silence():
    world = World()
    world.play(MUSIC, 26)
    assert world.dancing
    world.play(None, 4)
    assert world.names("stop_dance") == []
    world.play(None, 1)  # five seconds since the last clear second
    assert [a for _, n, a in world.calls if n == "stop_dance"] == ["music ended"]
    world.second(None)
    assert world.ctl.state == "spent"


def test_the_same_music_never_starts_a_second_session():
    world = World()
    world.play(MUSIC, 26)
    world.dancing = False  # the dance reached its 20 s cap
    world.play(MUSIC, 120)  # the song goes on
    assert len(world.names("nod")) == 1
    assert len(world.names("request_dance")) == 1
    world.play(None, 11)
    assert world.ctl.state == "idle"  # quiet re-arms it


def test_a_dance_that_the_runner_refuses_spends_the_session():
    world = World()
    world.dance_refusal = "the unit is not upright"
    world.play(MUSIC, 26)
    assert world.ctl.state == "spent"
    assert not world.dancing


# ------------------------------------------------------------------ gates


@pytest.mark.parametrize(
    "change",
    [
        {"night": True},
        {"awake": False},
        {"in_turn": True},
        {"estop": True},
        {"full_quiet": "muted"},
        {"offline": True},
        {"connected": False},
        {"upright": False},
        {"camera_cue": True},
        {"live_cue": True},
    ],
)
def test_no_nod_in_a_blocked_situation(change):
    world = World()
    world.sit = replace(world.sit, **change)
    world.play(MUSIC, 40)
    assert world.names("nod") == [] and world.names("request_dance") == []
    assert world.ctl.state == "spent"


def test_battery_tiers_on_battery():
    full = World()
    full.sit = replace(full.sit, battery_percent=40)
    full.play(MUSIC, 26)
    assert full.dancing

    nod_only = World()
    nod_only.sit = replace(nod_only.sit, battery_percent=39)
    nod_only.play(MUSIC, 40)
    assert len(nod_only.names("nod")) == 1 and nod_only.names("request_dance") == []

    edge = World()
    edge.sit = replace(edge.sit, battery_percent=20)
    edge.play(MUSIC, 40)
    assert len(edge.names("nod")) == 1 and edge.names("request_dance") == []

    low = World()
    low.sit = replace(low.sit, battery_percent=19)
    low.play(MUSIC, 40)
    assert low.calls == []

    unknown = World()
    unknown.sit = replace(unknown.sit, battery_percent=None, charging=None)
    unknown.play(MUSIC, 40)
    assert unknown.calls == []


def test_while_charging_the_battery_level_does_not_matter_but_the_stages_do():
    world = World()
    world.sit = replace(world.sit, battery_percent=5, charging=True)
    world.play(MUSIC, 26)
    assert world.names("nod") and world.dancing


def test_a_low_battery_flag_blocks_everything():
    world = World()
    world.sit = replace(world.sit, battery_low=True)
    world.play(MUSIC, 40)
    assert world.calls == []


def test_a_turn_or_a_touch_during_the_wait_ends_the_session():
    world = World()
    world.play(MUSIC, 10)
    world.sit = replace(world.sit, in_turn=True)
    world.second(MUSIC)
    assert world.ctl.state == "spent"
    world.sit = replace(world.sit, in_turn=False)
    world.play(MUSIC, 30)
    assert world.names("request_dance") == []

    touched = World()
    touched.play(MUSIC, 8)
    touched.ctl.on_events([Ev("head_touch", 0, {"tap": 1})], touched.t)
    assert touched.ctl.state == "spent"
    touched.play(MUSIC, 30)
    assert touched.names("request_dance") == []


def test_the_nods_own_motion_is_not_a_touch():
    world = World()
    world.play(MUSIC, 5)
    world.ctl.on_events([Ev("shake")], world.t + 0.5)
    assert world.ctl.state == "nod"
    world.ctl.on_events([Ev("shake")], world.t + 2.0)
    assert world.ctl.state == "spent"


def test_turning_the_setting_off_mid_session_stops_it():
    world = World()
    world.play(MUSIC, 26)
    assert world.dancing
    world.settings.auto = False
    world.second(MUSIC)
    assert world.names("stop_dance")
    world2 = World()
    world2.play(MUSIC, 10)
    world2.settings.auto = False
    world2.second(MUSIC)
    world2.play(MUSIC, 30)
    assert world2.names("request_dance") == []


def test_dancing_switched_off_entirely_silences_the_music_dance_too():
    world = World()
    world.settings.enabled = False
    world.play(MUSIC, 40)
    assert world.calls == []


# ------------------------------------------------------------------ caps and gaps


def test_ten_minutes_minimum_gap_after_a_dance():
    world = World()
    world.session()
    end = world.t
    world.play(MUSIC, 60)  # a new song a minute later
    assert len(world.names("nod")) == 1
    assert world.ctl.state == "spent"
    world.play(None, 20)
    assert world.ctl.state == "idle"
    world.t = end + 601.0
    world.session()
    assert len(world.names("nod")) == 2


def test_three_dances_an_hour_and_ten_a_day():
    world = World()
    for i in range(3):
        world.session()
        world.t += 601.0  # past the gap
    world.session()  # the fourth within the hour: no nod, no dance
    assert len(world.names("request_dance")) == 3
    assert len(world.names("nod")) == 3
    # a day: one dance every 70 minutes is under the hourly cap and runs into the daily one
    day = World()
    for _ in range(12):
        day.session()
        day.t += 4200.0
    assert len(day.names("request_dance")) == 10


def test_the_caps_age_out():
    world = World()
    for _ in range(3):
        world.session()
        world.t += 601.0
    world.t += 3600.0
    world.session()
    assert len(world.names("request_dance")) == 4


def test_nods_alone_are_spaced_two_minutes_apart():
    world = World()
    world.sit = replace(world.sit, battery_percent=30)  # nod only
    world.session(10)
    first = world.names("nod")
    world.play(MUSIC, 30)  # still inside the two minutes
    assert world.names("nod") == first
    world.play(None, 15)
    world.t += 130.0
    world.session(10)
    assert len(world.names("nod")) == 2


# ------------------------------------------------------------------ the test command and logging


def test_music_test_runs_the_whole_chain_without_music_and_the_setting_off():
    world = World(auto=False)
    ok, why = world.ctl.start_test(world.t)
    assert ok and why == ""
    world.play(None, 30)  # the unit hears nothing; the test feeds its own seconds
    assert world.names("nod") and world.names("request_dance")
    assert world.dancing
    world.play(None, 40)  # the scripted music stops after a minute; the dance ends on silence
    assert world.names("stop_dance")
    assert world.ctl.state in ("spent", "idle")


def test_music_test_counts_toward_no_cap_and_ignores_the_gap():
    world = World(auto=True)
    for _ in range(4):
        ok, _ = world.ctl.start_test(world.t)
        assert ok
        world.play(None, 62)
        world.dancing = False
        world.play(None, 20)
    assert len(world.names("request_dance")) == 4
    world.session()  # a real session still has its whole allowance and no recent dance
    assert len(world.names("request_dance")) == 5


def test_music_test_fast_compresses_the_waits():
    world = World(auto=False)
    ok, _ = world.ctl.start_test(world.t, fast=True)
    assert ok
    world.play(None, 10)
    assert world.names("request_dance")
    assert FAST.nod_to_build_s < M.NORMAL.nod_to_build_s


@pytest.mark.parametrize(
    "change", [{"night": True}, {"in_turn": True}, {"estop": True}, {"awake": False}]
)
def test_music_test_obeys_the_safety_gates(change):
    world = World(auto=False)
    world.sit = replace(world.sit, **change)
    ok, why = world.ctl.start_test(world.t)
    assert not ok and why
    world.play(None, 40)
    assert world.calls == []


def test_music_test_is_refused_while_dancing_is_off_or_a_session_runs():
    world = World(auto=False)
    world.settings.enabled = False
    assert world.ctl.start_test(world.t)[0] is False
    busy = World()
    busy.play(MUSIC, 6)
    assert busy.ctl.start_test(busy.t)[0] is False


def test_the_log_has_a_line_per_stage_detection_and_minute(caplog):
    world = World()
    with caplog.at_level(logging.INFO, logger="maipai_body.bodies.stackchan.music_dance"):
        world.play(MUSIC, 26)
        world.play(None, 8)
        world.play(NO_BEAT, 60)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "detected clear music for 4 s (tempo 120 bpm, confidence 80%)" in text
    assert "stage idle -> nod" in text
    assert "stage nod -> watch" in text
    assert "stage watch -> show" in text
    assert "stage show -> spent" in text
    assert (
        "music minute:" in text and "feature windows" in text and "false-start candidates" in text
    )


def test_false_start_candidates_are_counted_in_the_minute_line(caplog):
    world = World()
    with caplog.at_level(logging.INFO, logger="maipai_body.bodies.stackchan.music_dance"):
        for _ in range(5):  # three music-like seconds, then speech: never reaches four
            world.play(MUSIC, 3)
            world.play(SPEECH, 4)
        world.play(SPEECH, 40)
    lines = [r.getMessage() for r in caplog.records if "music minute" in r.getMessage()]
    assert lines and any("5 false-start" in line or "4 false-start" in line for line in lines)


# ------------------------------------------------------------------ the plan on the real runner


class RunnerWorld:
    def __init__(self, **situation) -> None:
        self.t = 100.0
        self.sit = DanceSituation(battery_percent=90, charging=False, **situation)
        self.log: list[tuple[float, str, object]] = []
        self.runner = DanceRunner(
            DanceHooks(
                start_dance=self.rec("dance"),
                stop_dance=self.rec("stop_dance"),
                show_face=self.rec("face"),
                write_ring=self.rec("ring"),
                take_ring=self.rec("take_ring"),
                give_ring_back=self.rec("give_ring_back"),
                level_head=self.rec("level"),
                situation=lambda: self.sit,
                hold=self.rec("hold"),
            ),
            DanceSettings(),
            clock=lambda: self.t,
            wait=self._wait,
            spawn=lambda fn: fn(),
        )
        self.start = self.t

    def _wait(self, seconds):
        self.t += seconds
        return self.runner._stop.is_set()

    def rec(self, name):
        return lambda *a: self.log.append((round(self.t - self.start, 2), name, a))


def test_the_auto_plan_plays_a_build_up_then_the_dance_then_levels_the_head():
    world = RunnerWorld()
    reply = world.runner.request("auto", AUTO_PLAN)
    assert reply.started and reply.line == ""  # no spoken line
    assert world.runner.last_end_reason == "done"
    dances = [(t, a[0]) for t, n, a in world.log if n == "dance"]
    assert [d for _, d in dances][:2] == ["happy", "happy"]
    assert dances[2][1] == "robot" and dances[2][0] == pytest.approx(M.BUILD_S, abs=0.3)
    faces = [a for _, n, a in world.log if n == "face"]
    assert faces[-1] == ("neutral",) and ("surprised",) in faces and ("wink",) in faces
    assert "level" in [n for _, n, _ in world.log] and "stop_dance" in [n for _, n, _ in world.log]
    assert world.t - 100.0 == pytest.approx(M.TOTAL_S, abs=0.5)
    assert M.TOTAL_S - M.BUILD_S == 20.0


def test_the_auto_plan_never_runs_at_night_and_a_touch_ends_it():
    world = RunnerWorld(night=True)
    reply = world.runner.request("auto", AUTO_PLAN)
    assert not reply.started and "night" in reply.why
    day = RunnerWorld()
    day.runner.request("auto", AUTO_PLAN)
    assert day.runner.last_end_reason == "done"


def test_the_build_up_ring_is_dark_then_a_dim_glow_then_the_show():
    assert M._ring(0, 0.0) is None
    assert M._ring(10, M.GLOW_FROM_S - 0.1) is None
    glow = M._ring(3, M.GLOW_FROM_S + 0.1)
    show = M._ring(3, M.BUILD_S + 0.5)
    assert glow is not None and show is not None
    assert len({p for p in glow if p != (0, 0, 0)}) >= 2
    assert max(max(p) for p in glow) < max(max(p) for p in show)  # 0.2 against 0.5
    assert M.glow_frame(0) != M.glow_frame(2)  # always moving
    status = [tuple(c) for c in RING_RGB.values()]
    for pixel in glow:
        assert pixel[0] < 100 or pixel[1] > 0  # never a red
        assert tuple(pixel) not in status


def test_the_music_dance_quiet_room_wiring_ticks_without_events():
    """tick() with nothing ever received is harmless."""
    world = World()
    world.play(None, 600)
    assert world.calls == []


# ------------------------------------------------------------------ the live wiring, with fakes


def test_the_companion_keeps_the_music_numbers_as_integers_and_knows_the_kind():
    from maipai_body.bodies.stackchan.companion import DIAGNOSTIC_KINDS, StackChanCompanion

    assert {"music_feat", "music_stats"} <= DIAGNOSTIC_KINDS
    companion = StackChanCompanion(
        lambda name, args: [
            {
                "kind": "music_feat",
                "at_ms": 9,
                "lv": 2400,
                "b0": 40,
                "bpm": 120,
                "tc": 80,
                "muted": False,
            }
        ]
    )
    (event,) = companion.poll_events()
    assert event.kind == "music_feat"
    assert event.extra == {"lv": 2400, "b0": 40, "bpm": 120, "tc": 80, "muted": False}


def _real_behavior():
    from maipai_body.app import StackChanBehavior
    from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
    from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient

    behavior = StackChanBehavior(StackChanRobotAdapter(FakeStackChanDeviceClient()).robot)
    behavior._rest = type("Rest", (), {"stage": "awake"})()
    return behavior


def _wire(behavior, *, battery=90, night=False):
    from types import SimpleNamespace

    from maipai_body.bodies.stackchan.light_service import StackChanLightService
    from maipai_body.bodies.stackchan.music_dance_wiring import wire_music_dance
    from maipai_body.bodies.stackchan.ring_indicator import StackChanRingIndicator

    calls: list = []
    clock = {"t": 7000.0}
    client = SimpleNamespace(
        get_battery_status=lambda: {"percent": battery, "charging": False},
        companion=lambda: SimpleNamespace(
            dance=lambda name: calls.append(("dance", name)),
            stop_dance=lambda: calls.append(("stop_dance",)),
        ),
    )
    robot = SimpleNamespace(estop_engaged=False, leds=SimpleNamespace(many=lambda updates: None))
    voice = SimpleNamespace(robot=SimpleNamespace(client=client, robot=robot))
    light = StackChanLightService(StackChanRingIndicator(lambda rgb: None), minute=lambda: 12 * 60)
    from maipai_body.bodies.stackchan.dance_wiring import wire_dance
    from maipai_body.bodies.stackchan.head_commands import HeadCommander

    faces: list = []
    behavior.show_face = faces.append
    runner = wire_dance(
        voice=voice,
        behavior=behavior,
        light=light,
        night=SimpleNamespace(night=night),
        head_commander=HeadCommander(lambda *a: None),
        level_head=lambda: calls.append(("level",)),
        device_connected=lambda: True,
    )
    runner._clock = lambda: clock["t"]
    runner._wait = lambda s: clock.__setitem__("t", clock["t"] + s) or runner._stop.is_set()
    runner._spawn = lambda f: f()
    moves: list = []
    controller = wire_music_dance(
        behavior=behavior,
        runner=runner,
        move_head=lambda yaw, pitch, speed: moves.append((yaw, pitch, speed)),
        centre_pitch=5,
        speed=120,
        clock=lambda: clock["t"],
        start_ticker=False,
    )
    controller._spawn = lambda f: f()
    controller._choose_face = lambda: "happy"
    return SimpleNamespace(
        controller=controller, calls=calls, clock=clock, faces=faces, moves=moves, runner=runner
    )


def _music_event(feat: MusicFeat = MUSIC):
    return Ev(
        "music_feat",
        1,
        {
            "lv": feat.lv, "b0": 40, "b1": 35, "b2": 18, "b3": 7, "bpm": feat.bpm, "tc": feat.tc,
            "fl": feat.fl, "zc": feat.zc, "zs": feat.zs, "mo": feat.mo, "ps": feat.ps, "on": 70,
        },
    )  # fmt: skip


def test_behavior_routes_music_features_to_the_controller_and_not_to_the_touch_filter():
    behavior = _real_behavior()
    try:
        w = _wire(behavior)
        w.controller.settings.auto = True
        batches = [[], *([[_music_event()]] * 6)]
        behavior.event_poll = lambda: batches.pop(0) if batches else []
        reactions: list = []
        behavior.reaction = reactions.append
        t = {"now": 0.0}
        behavior.wake_on_touch(t["now"])  # the first look drains
        for _ in range(6):
            t["now"] += 1.0
            w.clock["t"] += 1.0
            behavior.wake_on_touch(t["now"])
        assert w.controller.state == "nod"  # four seconds of music: the nod
        assert w.moves and w.moves[-1] == (0, 5, 120)  # level again after the nod
        assert w.faces[0] == "happy"
        assert reactions == []  # a music number is never a touch reaction
        assert not w.calls  # no firmware dance yet
    finally:
        behavior.close()


def test_the_first_look_after_a_pause_only_drains_old_music_features():
    behavior = _real_behavior()
    try:
        w = _wire(behavior)
        w.controller.settings.auto = True
        batches = [[_music_event()] * 10]
        behavior.event_poll = lambda: batches.pop(0) if batches else []
        behavior.wake_on_touch(0.0)
        assert w.controller._windows == 0
    finally:
        behavior.close()


def test_wiring_the_whole_chain_ends_in_the_firmware_dance_and_a_touch_stops_it():
    behavior = _real_behavior()
    try:
        w = _wire(behavior)
        w.controller.settings.auto = True
        behavior.event_poll = lambda: []
        # drive the controller's own clock; the runner's fake clock advances in the same step
        for _ in range(26):
            w.clock["t"] += 1.0
            behavior.music_feat(_music_event().extra, w.clock["t"])
            w.controller.tick(w.clock["t"])
        assert [c for c in w.calls if c[0] == "dance"][:2] == [
            ("dance", "happy"),
            ("dance", "happy"),
        ]
        assert ("stop_dance",) in w.calls and w.faces[-1] == "neutral"
    finally:
        behavior.close()


def test_the_hub_music_test_command_answers_and_a_busy_or_blocked_unit_refuses():
    behavior = _real_behavior()
    try:
        w = _wire(behavior)
        assert behavior.music_command({}) == {"music_test": "started", "why": ""}
        again = behavior.music_command({})
        assert again["music_test"] == "refused" and again["why"]
        behavior2 = _real_behavior()
        try:
            _wire(behavior2, night=True)
            assert behavior2.music_command({})["music_test"] == "refused"
            assert "night" in behavior2.music_command({})["why"]
        finally:
            behavior2.close()
        assert w.controller.testing
    finally:
        behavior.close()


def test_unready_music_command_default_refuses():
    behavior = _real_behavior()
    try:
        assert behavior.music_command({}) == {
            "music_test": "refused",
            "why": "the music dance is not ready",
        }
    finally:
        behavior.close()


def test_dance_settings_read_the_two_new_keys_and_default_off_medium():
    settings = DanceSettings()
    assert settings.auto is False and settings.auto_sensitivity == "medium"
    settings.apply({"robot.dance.auto": True, "robot.dance.auto_sensitivity": "high"})
    assert settings.auto is True and settings.auto_sensitivity == "high"
    settings.apply({"robot.dance.auto": "yes", "robot.dance.auto_sensitivity": "loud"})
    assert settings.auto is True and settings.auto_sensitivity == "high"  # bad values are ignored
    settings.apply({"robot.dance.auto": False})
    assert settings.auto is False
