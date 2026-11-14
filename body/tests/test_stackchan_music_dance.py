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


# the mechanics tests use the old waits (4 s music, 20 s to the dance, 4.5 s silence);
# the shipped defaults are checked by the tests that pass `timing=M.NORMAL`
LEGACY_TIMING = M.Timing(detect_s=4.0, nod_to_build_s=20.0, end_silence_s=4.5)


class World:
    """A controller on a fake clock with recording hooks and a scripted situation."""

    def __init__(
        self,
        *,
        auto: bool = True,
        sensitivity: str = "medium",
        timing: M.Timing | None = None,
        **situation,
    ) -> None:
        self.t = 5000.0
        self.sit = DanceSituation(**{"battery_percent": 90, "charging": False, **situation})
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
            stop_bob=lambda: self.calls.append((self.t, "stop_bob", None)),
            wonder=lambda: self.calls.append((self.t, "wonder", None)),
        )
        self.ctl = MusicDance(
            hooks,
            self.settings,
            spawn=lambda fn: fn(),
            choose_face=lambda: next(self.faces),
            timing=timing or LEGACY_TIMING,
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
        self.play(None, 75)  # quiet: the session gap (60 s) passes, the session ends and re-arms


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
    assert judge(replace(SPEECH, tc=90), sensitivity).why == "speech_like_modulation"
    assert judge(NOISE, sensitivity).why == "too_flat"
    assert judge(QUIET_MUSIC, sensitivity).why == "below_level_gate"
    assert judge(NO_BEAT, sensitivity).why == "weak_beat"
    assert judge(replace(MUSIC, muted=True), sensitivity).why == "self_hearing_blank"
    assert judge(replace(MUSIC, bpm=40, lv=700), sensitivity).why == "tempo_out_of_range"
    assert judge(replace(MUSIC, bpm=200, lv=700), sensitivity).why == "tempo_out_of_range"


def test_pauses_with_a_loose_beat_are_speech_but_a_steady_sparse_beat_is_music():
    assert judge(TALK_PAUSES, "high").why == "speech_like_pauses"
    assert judge(replace(MUSIC, ps=95, tc=90), "medium").music  # a click track


def test_sensitivity_moves_the_beat_bar():
    weak = replace(MUSIC, tc=16, lv=700)
    assert not judge(weak, "low").music
    assert not judge(weak, "medium").music
    assert judge(weak, "high").music
    assert judge(
        replace(MUSIC, tc=24, lv=700), "medium"
    ).music  # a real song at 1 m: tc 9 to 56, median 24
    assert not judge(replace(MUSIC, tc=24, lv=700), "low").music
    assert judge(
        replace(MUSIC, fl=80, lv=700), "medium"
    ).music  # the same song measured flatness 47 to 85


def test_a_bright_song_keeps_a_running_dance_alive():
    bright = replace(MUSIC, tc=10, fl=95, lv=700)
    assert not judge(bright, "medium").music
    assert judge(bright, "medium", relaxed=True).music


def test_a_running_stage_judges_a_little_more_gently():
    dip = replace(MUSIC, tc=17, lv=700)
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


def test_the_nod_goes_on_as_bobbing_and_the_face_is_restored_when_the_session_ends():
    world = World()
    world.play(MUSIC, 5)
    world.play(MUSIC, 3)
    assert world.ctl.state == "watch"
    assert world.names("restore_face") == []  # the head keeps bobbing with the happy face
    world.play(None, 30)  # the music stops before the full dance
    assert world.ctl.state in ("spent", "idle")
    assert world.names("stop_bob") and world.names("restore_face")


def test_a_run_of_music_with_one_missed_second_still_counts():
    world = World()
    for feat in (MUSIC, MUSIC, MUSIC, None, MUSIC, MUSIC):
        world.second(feat)
    assert world.names("nod") == [5.0]


def test_a_gap_resets_the_count():
    world = World()
    world.play(MUSIC, 3)
    world.play(NO_BEAT, 3)  # a gap without a beat (speech would also trip the talker rule)
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
    world.play(None, 9)
    assert world.names("request_dance") == []
    assert world.ctl.state == "spent"


def test_the_dance_pauses_after_four_and_a_half_seconds_of_silence():
    world = World()
    world.play(MUSIC, 26)
    assert world.dancing
    world.play(None, 4)
    assert world.names("stop_dance") == []
    world.play(None, 1)  # four and a half seconds since the last clear second
    assert [a for _, n, a in world.calls if n == "stop_dance"] == ["music ended"]
    world.second(None)
    assert world.ctl.state == "break"  # the round ended; the session waits for the music to return
    world.play(None, 60)  # a minute without music: the session is over
    assert world.ctl.state in ("spent", "idle")


def test_the_same_music_never_starts_a_second_session():
    world = World()
    world.play(MUSIC, 26)
    world.dancing = False  # the dance reached its 20 s cap
    world.play(MUSIC, 120)  # the song goes on
    assert len(world.names("nod")) == 1  # one nod, one session
    assert len(world.names("request_dance")) >= 2  # the song goes on: more dance rounds
    world.play(None, 75)
    assert world.ctl.state == "idle"  # a minute of quiet ends the session and re-arms it


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


def test_muted_music_dance_refuses_new_start_and_stops_running_dance_as_muted():
    blocked = World(muted=True)
    blocked.play(MUSIC, 30)
    assert blocked.names("request_dance") == []

    running = World()
    running.play(MUSIC, 25)
    assert running.names("request_dance")
    running.sit = replace(running.sit, muted=True)
    running.ctl.tick(running.t + 1)
    assert [arg for _, name, arg in running.calls if name == "stop_dance"] == ["muted"]


# ------------------------------------------------------------------ caps and gaps


def test_two_minutes_minimum_gap_after_a_session():
    world = World()
    world.session()
    end = world.t
    world.play(MUSIC, 60)  # a new song a minute later
    assert len(world.names("nod")) == 1
    assert world.ctl.state == "spent"
    world.play(None, 75)
    assert world.ctl.state == "idle"
    world.t = end + 601.0
    world.session()
    assert len(world.names("nod")) == 2


def test_there_are_no_hourly_or_daily_caps():
    world = World()
    for _ in range(12):
        world.session()
        world.t += 121.0  # past the gap
    assert len(world.names("nod")) == 12  # twelve sessions in about as many minutes, none refused


def _song(world: World, seconds: int) -> None:
    """Music for ``seconds`` with a runner that finishes each dance on its own (30 s the build-up
    and dance, 20 s a dance-only round)."""
    started = -1.0
    length = 0.0
    for _ in range(seconds):
        before = len(world.names("request_dance"))
        world.second(MUSIC)
        if len(world.names("request_dance")) > before:
            started = world.t
            length = 30.0 if world.ctl.plan == "full" else 20.0
        if world.dancing and started >= 0 and world.t - started >= length:
            world.dancing = False


def test_a_forty_minute_song_dances_in_cycles_with_breaks_and_never_ends():
    world = World(charging=True)
    _song(world, 40 * 60)
    states = [t for t in world.names("request_dance")]
    assert len(states) > 40  # rounds all the way through
    assert len(world.names("nod")) == 1
    assert world.ctl.state in ("show", "break")  # still in the session after forty minutes
    assert world.ctl._cycle >= 6  # a block of 5 minutes and a break of 90 s: about one every 6.5


def test_a_gap_between_songs_under_a_minute_keeps_the_session_and_over_ends_it():
    world = World(charging=True)
    _song(world, 60)
    world.play(None, 50)  # the next song starts within a minute
    _song(world, 10)
    assert world.ctl.state in ("show", "break")
    assert len(world.names("nod")) == 1
    world.dancing = False
    world.play(None, 70)  # a long gap: the session is over
    assert world.ctl.state in ("spent", "idle")


def test_on_battery_the_block_is_shorter():
    usb = World(charging=True)
    _song(usb, 400)
    batt = World(charging=False)
    _song(batt, 400)
    assert batt.ctl._cycle > usb.ctl._cycle


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
    world.session()  # a real session still has no recent dance in the way
    assert len(world.names("request_dance")) >= 5


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
    assert "stage show -> break" in text
    assert "stage break -> spent" in text
    assert "music minute:" in text and "why[music:" in text and "lv=" in text


def test_false_start_candidates_are_counted_in_the_minute_line(caplog):
    world = World()
    with caplog.at_level(logging.INFO, logger="maipai_body.bodies.stackchan.music_dance"):
        for _ in range(5):  # three music-like seconds, then speech: never reaches four
            world.play(MUSIC, 3)
            world.play(NO_BEAT, 4)
        world.play(SPEECH, 40)
    lines = [r.getMessage() for r in caplog.records if "music minute" in r.getMessage()]
    assert lines and any("false=5" in line or "false=4" in line for line in lines)


def test_window_rejections_are_reasoned_rate_limited_and_quiet_is_silent(caplog):
    world = World()
    with caplog.at_level(logging.INFO, logger="maipai_body.bodies.stackchan.music_dance"):
        world.play(QUIET_MUSIC, 8)
        world.play(NO_BEAT, 12)
    rejected = [r.getMessage() for r in caplog.records if "window rejected:" in r.getMessage()]
    assert len(rejected) == 3
    assert all("reason=weak_beat" in line and "lv=" in line and "bpm=" in line for line in rejected)


def test_minute_logs_counts_and_feature_min_median_max(caplog):
    world = World()
    with caplog.at_level(logging.INFO, logger="maipai_body.bodies.stackchan.music_dance"):
        world.second(replace(MUSIC, lv=1200, on=10))
        world.second(replace(MUSIC, lv=1800, on=30))
        world.second(replace(MUSIC, lv=2400, on=50))
        world.play(NO_BEAT, 60)
    lines = [r.getMessage() for r in caplog.records if "music minute:" in r.getMessage()]
    assert lines
    line = lines[0]
    assert "weak_beat:" in line and "music:" in line
    assert "lv=1200/2400/2400" in line  # Includes the later scripted no-beat windows.
    assert len(line) <= 400


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
    assert faces[-1] == ("neutral",) and ("surprised",) in faces and ("wink",) not in faces
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
        w.controller._timing = LEGACY_TIMING  # the chain is timed for the old waits
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
        # the dance ends with the usual face or, when the music is gone, the curious look
        assert ("stop_dance",) in w.calls and w.faces[-1] in ("neutral", "thinking")
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


# ---------------------------------------------------------------- the unit's music switch


class _Unit:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = False

    def __call__(self, name: str, arguments: dict) -> object:
        if self.fail:
            raise OSError("unit unreachable")
        self.calls.append((name, dict(arguments)))
        return {"ok": True}


def _switch(unit: _Unit, state: dict, clock: list[float]):
    from maipai_body.bodies.stackchan.music_dance_wiring import MusicFeatureSwitch

    return MusicFeatureSwitch(
        unit,
        auto=lambda: state["auto"],
        silenced=lambda: state["silenced"],
        clock=lambda: clock[0],
    )


def test_the_unit_analyses_music_only_while_the_setting_is_on_and_it_is_not_silenced():
    unit, state, clock = _Unit(), {"auto": False, "silenced": False}, [0.0]
    switch = _switch(unit, state, clock)
    switch.on_session()  # connect with the setting off: the unit is told off
    assert unit.calls == [("self.music.set", {"enabled": False})]
    switch.sync()
    assert len(unit.calls) == 1  # no repeat while nothing changed
    state["auto"] = True
    switch.apply_settings({"robot.dance.auto": True})
    assert unit.calls[-1] == ("self.music.set", {"enabled": True})
    state["silenced"] = True  # muted or full quiet
    switch.apply_settings({"robot.muted": True})
    assert unit.calls[-1] == ("self.music.set", {"enabled": False})
    state["silenced"] = False
    switch.apply_settings({"robot.muted": False})
    assert unit.calls[-1] == ("self.music.set", {"enabled": True})
    state["auto"] = False
    switch.apply_settings({"robot.dance.auto": False})
    assert unit.calls[-1] == ("self.music.set", {"enabled": False})


def test_a_reconnect_states_the_switch_again_and_a_failed_call_is_retried():
    unit, state, clock = _Unit(), {"auto": True, "silenced": False}, [0.0]
    switch = _switch(unit, state, clock)
    unit.fail = True
    switch.apply_settings({})
    assert switch.sent is None and unit.calls == []
    unit.fail = False
    clock[0] = 5.0
    switch.sync()  # too soon after the failure
    assert unit.calls == []
    clock[0] = 20.0
    switch.sync()
    assert unit.calls == [("self.music.set", {"enabled": True})]
    switch.on_session()  # a reboot forgot nothing in flash, but the host says it again anyway
    assert len(unit.calls) == 2


def test_the_firmware_patch_keeps_music_analysis_off_until_the_host_turns_it_on():
    from pathlib import Path

    patch = (
        Path(__file__).resolve().parents[1]
        / "maipai_body/bodies/stackchan/firmware/patches/100-music-features.patch"
    ).read_text()
    assert "std::atomic<bool> s_enabled{false};" in patch  # off at boot
    # The tap leaves before any analysis or counting while off.
    tap = patch.split("void maipai_music_tap(", 1)[1]
    assert tap.index("!s_enabled.load()") < tap.index("send_reset()")
    assert 'tagInfo(_tag, "music features {}", enabled ? "on" : "off")' in patch  # the boot log
    assert '"self.music.set"' in patch
    assert 'kNvsNamespace = "mp_music"' in patch  # never the websocket namespace


def test_a_loud_steady_song_with_a_wandering_tempo_is_music():
    wandering = replace(MUSIC, tc=15, fl=90, bpm=187, mo=20, ps=5)
    assert judge(wandering, "medium").why == "music"
    assert judge(wandering, "high").music
    assert judge(wandering, "low").why == "weak_beat"
    assert not judge(replace(wandering, mo=45), "medium").music  # speech modulation
    assert not judge(replace(wandering, ps=30), "medium").music  # pauses
    assert not judge(replace(wandering, fl=98), "medium").music  # noise
    assert not judge(replace(wandering, lv=600), "medium").music  # too quiet for this path


def test_the_notes_follow_the_stages():
    world = World()
    shown: list[int] = []
    hooks = world.ctl._hooks
    hooks.notes = shown.append
    world.play(MUSIC, 30)
    assert shown[0] == 1  # the nod
    assert 0 in shown  # cleared when the nod ends
    assert 3 in shown  # the dance
    world.play(None, 80)
    assert shown[-1] == 0  # and gone when it ends


def test_a_talker_over_background_music_is_not_a_song():
    world = World()
    talk = replace(MUSIC, ps=30, mo=20)  # a beat, but a third of the frames are speech pauses
    song = replace(MUSIC, ps=3, mo=15)
    for i in range(30):
        world.second(talk if i % 2 == 0 else replace(song, ps=26))
    assert world.names("nod") == []
    assert world.names("request_dance") == []
    clean = World()
    clean.play(song, 30)
    assert clean.names("nod")  # a plain song still nods


def test_a_song_with_a_few_quiet_seconds_still_dances():
    world = World()
    for i in range(40):
        world.second(replace(MUSIC, ps=30) if i % 8 == 0 else MUSIC)
    assert world.names("nod")


def test_the_break_is_a_slow_mood_the_dance_never_stops_while_music_plays():
    world = World(charging=True)
    _song(world, 20 * 60)
    starts = world.names("request_dance")
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    assert max(gaps) <= 31.0  # a new round at least every round: no 90 s of standing still
    assert world.ctl._cycle >= 3  # the slow mood and the slow start came round more than once
    assert not [1 for _, n, a in world.calls if n == "stop_dance" and a == "music ended"]


def test_no_music_means_no_dance_and_it_starts_again_when_music_returns():
    world = World(charging=True)
    _song(world, 60)
    world.play(None, 20)  # the music stops for 20 s: the dance stops, the session stays
    assert not world.dancing
    assert world.ctl.state == "break"
    before = len(world.names("request_dance"))
    world.play(None, 20)
    assert len(world.names("request_dance")) == before  # nothing starts without music
    _song(world, 10)
    assert len(world.names("request_dance")) > before  # clear music again: it dances


def test_a_pause_by_the_forehead_stops_the_dance_and_nothing_restarts_it():
    world = World(charging=True)
    _song(world, 60)
    world.sit = replace(world.sit, full_quiet="quiet")
    world.play(MUSIC, 5)
    n = len(world.names("request_dance"))
    world.play(MUSIC, 60)
    assert len(world.names("request_dance")) == n


def test_after_a_pause_it_goes_right_back_to_the_mood_it_was_in():
    # fast: a dance round was running
    fast = World(charging=True)
    _song(fast, 40)
    assert fast.ctl.plan in ("full", "dance")
    fast.play(None, 6)  # no music: paused
    assert fast.ctl.state == "break" and not fast.dancing
    before = len(fast.names("request_dance"))
    fast.second(MUSIC)  # the music picks up
    assert len(fast.names("request_dance")) == before + 1
    assert fast.ctl.state == "show" and fast.ctl.plan == "dance"
    # slow: the slow mood was running
    slow = World(charging=True)
    _song(slow, 350)  # past the 5 minute block into the slow mood
    assert slow.ctl.state == "calm"
    slow.play(None, 6)
    assert slow.ctl.state == "break"
    slow.second(MUSIC)
    assert slow.ctl.state == "calm" and slow.ctl.plan == "calm" and slow.dancing
    # medium: paused during the build-up of a slow start
    medium = World(charging=True)
    medium.play(MUSIC, 25)  # the nod, the wait, the dance request (full plan) at about 25 s
    assert medium.ctl.plan == "full" and medium.ctl.state == "show"
    medium.play(None, 6)  # the music stops during the build-up: the runner is stopped, then paused
    assert medium.ctl.state == "break"
    medium.second(MUSIC)
    assert medium.ctl.state == "show" and medium.ctl.plan == "full"


def test_the_shipped_waits_start_quickly_and_stop_quickly():
    t = M.NORMAL
    assert (t.detect_s, t.nod_to_build_s, t.end_silence_s) == (3.0, 15.0, 3.0)
    world = World(timing=M.NORMAL, charging=True)
    world.play(MUSIC, 4)  # music at +1, +2, +3, +4: a 3 s run: the nod at +4
    assert world.names("nod") == [4.0]
    world.play(MUSIC, 15)  # the dance starts 15 s after the nod, the head bobbing until then
    assert world.names("request_dance") == [19.0]
    world.play(None, 2)
    assert world.dancing
    world.play(None, 1)  # three seconds without music: the dance stops
    assert [a for _, n, a in world.calls if n == "stop_dance"] == ["music ended"]


def test_when_the_music_goes_the_robot_wonders_once_where_it_went():
    world = World(charging=True)
    _song(world, 60)
    assert world.names("wonder") == []
    world.play(None, 6)  # the music stops: the dance stops and the curious look shows, once
    assert len(world.names("wonder")) == 1
    world.play(None, 70)  # the long silence ends the session: no second look
    assert len(world.names("wonder")) == 1
    quiet = World(charging=True)
    quiet.play(MUSIC, 5)
    quiet.play(
        None, 30
    )  # the music stops while the head was only nodding: no dance to wonder about
    assert quiet.names("wonder") == []
