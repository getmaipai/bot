"""SELF-SCENE-02: the battery and heat ladder on scripted discharge and heat curves."""

from __future__ import annotations

import json

from maipai_body.presence.carry_reaction import PresenceEntry
from maipai_body.presence.power import (
    LINE_IDS,
    HeatLadder,
    HeatLevel,
    PowerLadder,
    PowerLevel,
    Rung,
    child_pool,
    line_id,
)
from maipai_body.presence.thermal import ThermalGovernor, ThermalMonitor
from maipai_body.settings_keys import POWER_WARN_AT_KEY, power_warn_at
from maipai_body.speech.offline_clips import MANIFEST_PATH, PHRASES, ClipPicker, load_manifest
from tests.test_run_loop import _make_loop

# ---- the ladder alone -------------------------------------------------------------------


def _discharge(ladder: PowerLadder, percents, *, near=True, quiet=False, start=0.0):
    """Feed a curve, 10 s a sample, and collect every line the body would say."""
    said: list[Rung] = []
    now = start
    for percent in percents:
        now += 10.0
        ladder.update(percent, False, now)
        rung = ladder.take_line(near=near, quiet=quiet, may_speak=True)
        if rung is not None:
            said.append(rung)
    return said


def test_warn_once_per_discharge_with_hysteresis():
    ladder = PowerLadder()
    # 21 no, 20 warns; wobbling 19..22 around the rung never earns a second line.
    assert _discharge(ladder, [25, 21, 20, 19, 22, 20, 18, 21, 19]) == [Rung.WARN]
    assert ladder.level is PowerLevel.WARN


def test_warn_level_clears_only_three_points_above():
    ladder = PowerLadder()
    ladder.update(20, False, 0)
    ladder.update(22, False, 1)
    assert ladder.level is PowerLevel.WARN
    ladder.update(23, False, 2)
    assert ladder.level is PowerLevel.OK


def test_warn_is_nothing_when_nobody_is_near_and_the_rung_is_spent():
    ladder = PowerLadder()
    assert _discharge(ladder, [21, 20, 19, 18], near=False) == []
    assert ladder.take_line(near=True, quiet=False, may_speak=True) is None


def test_degrade_at_15_is_silent():
    ladder = PowerLadder()
    assert _discharge(ladder, [20, 16]) == [Rung.WARN]
    assert not ladder.low_power
    assert _discharge(ladder, [15, 14], start=100.0) == []
    assert ladder.level is PowerLevel.DEGRADED
    assert ladder.low_power
    ladder.update(17, False, 200.0)  # 3 points of hysteresis: still degraded
    assert ladder.level is PowerLevel.DEGRADED
    ladder.update(18, False, 201.0)
    assert ladder.level is PowerLevel.WARN
    assert not ladder.low_power


def test_dock_ask_once_at_10():
    ladder = PowerLadder()
    assert _discharge(ladder, [30, 20, 15, 11, 10, 9, 12, 10, 9]) == [Rung.WARN, Rung.DOCK]


def test_goodbye_then_sleep_after_the_five_second_grace():
    ladder = PowerLadder()
    ladder.update(6, False, 0.0)
    ladder.update(5, False, 100.0)
    assert ladder.level is PowerLevel.SLEEP
    assert ladder.take_line(near=True, quiet=False, may_speak=True) is Rung.GOODBYE
    assert not ladder.sleep_due(104.9)
    assert ladder.sleep_due(105.0)


def test_charging_clears_every_state_and_the_counters():
    ladder = PowerLadder()
    assert _discharge(ladder, [20, 15, 10, 5]) == [Rung.WARN, Rung.DOCK, Rung.GOODBYE]
    ladder.update(6, True, 500.0)
    assert ladder.level is PowerLevel.OK
    assert not ladder.low_power
    assert not ladder.sleep_due(9999.0)
    # a new discharge earns every line again
    ladder.update(80, False, 600.0)
    assert _discharge(ladder, [20, 10, 5], start=700.0) == [Rung.WARN, Rung.DOCK, Rung.GOODBYE]


def test_no_line_in_quiet_hours_except_the_goodbye():
    ladder = PowerLadder()
    assert _discharge(ladder, [20, 15, 10, 9, 5], quiet=True) == [Rung.GOODBYE]


def test_the_dock_ask_waits_for_quiet_hours_to_end():
    ladder = PowerLadder()
    ladder.update(10, False, 0.0)
    assert ladder.take_line(near=True, quiet=True, may_speak=True) is None
    assert ladder.take_line(near=True, quiet=False, may_speak=True) is Rung.DOCK
    assert ladder.take_line(near=True, quiet=False, may_speak=True) is None


def test_a_turn_or_mute_defers_a_line_without_losing_it():
    ladder = PowerLadder()
    ladder.update(10, False, 0.0)
    assert ladder.take_line(near=True, quiet=False, may_speak=False) is None
    assert ladder.take_line(near=True, quiet=False, may_speak=True) is Rung.DOCK


def test_a_jump_past_rungs_says_only_the_deepest():
    ladder = PowerLadder()
    assert _discharge(ladder, [50, 4]) == [Rung.GOODBYE]


def test_unknown_readings_keep_the_state_and_the_failed_read_zero_is_unknown():
    ladder = PowerLadder()
    ladder.update(12, False, 0.0)
    ladder.update(None, None, 1.0)
    assert ladder.level is PowerLevel.DEGRADED
    ladder.update(0, False, 2.0)  # the firmware's failed read
    assert ladder.percent == 12 and ladder.level is PowerLevel.DEGRADED


def test_warn_at_is_admin_moved_and_clamped():
    ladder = PowerLadder(warn_at=30)
    assert _discharge(ladder, [31, 30]) == [Rung.WARN]
    assert PowerLadder(warn_at=3)._threshold(PowerLevel.WARN) == 16
    assert power_warn_at({}) == 20
    assert power_warn_at({POWER_WARN_AT_KEY: 25}) == 25
    assert power_warn_at({POWER_WARN_AT_KEY: 90}) == 50
    assert power_warn_at({POWER_WARN_AT_KEY: "x"}) == 20
    assert power_warn_at({POWER_WARN_AT_KEY: True}) == 20
    assert power_warn_at(None) == 20


# ---- heat -------------------------------------------------------------------------------


def test_heat_70_76_82_with_three_degrees_of_hysteresis():
    heat = HeatLadder()
    assert heat.update(69.9) is HeatLevel.NOMINAL
    assert heat.update(70.0) is HeatLevel.WARM
    assert heat.update(75.9) is HeatLevel.WARM
    assert heat.update(76.0) is HeatLevel.HOT
    assert heat.update(82.0) is HeatLevel.CRITICAL
    assert heat.motion_stopped
    assert heat.update(79.0) is HeatLevel.CRITICAL  # 3 C below: still critical
    assert heat.update(78.9) is HeatLevel.HOT
    assert not heat.motion_stopped
    assert heat.update(73.0) is HeatLevel.HOT
    assert heat.update(72.9) is HeatLevel.WARM
    assert heat.update(67.0) is HeatLevel.WARM
    assert heat.update(66.9) is HeatLevel.NOMINAL
    assert heat.update(None) is HeatLevel.NOMINAL


def test_critical_says_one_line_per_episode_and_respects_quiet_hours():
    heat = HeatLadder()
    heat.update(83.0)
    assert heat.take_line(quiet=True, may_speak=True) is None
    assert heat.take_line(quiet=False, may_speak=False) is None
    assert heat.take_line(quiet=False, may_speak=True) is Rung.HEAT
    assert heat.take_line(quiet=False, may_speak=True) is None
    heat.update(81.0)
    heat.update(83.0)  # wobbling inside the hysteresis band: same episode
    assert heat.take_line(quiet=False, may_speak=True) is None
    heat.update(70.0)  # cooled below the band: a new episode
    heat.update(83.0)
    assert heat.take_line(quiet=False, may_speak=True) is Rung.HEAT


def test_line_due_flags_track_owed_lines():
    power = PowerLadder()
    heat = HeatLadder()
    assert not power.has_line_due
    assert not heat.has_line_due
    power.update(20, False, 0.0)
    heat.update(82.0)
    assert power.has_line_due
    assert heat.has_line_due
    assert power.take_line(near=True, quiet=False, may_speak=True) is Rung.WARN
    assert heat.take_line(quiet=False, may_speak=True) is Rung.HEAT
    assert not power.has_line_due
    assert not heat.has_line_due


# ---- the line pools ---------------------------------------------------------------------


def test_the_pools_exist_in_the_manifest_with_both_wordings():
    manifest = load_manifest()
    picker = ClipPicker(manifest)
    for (rung, child), pool in LINE_IDS.items():
        assert pool in PHRASES, pool
        assert picker.variants(pool), f"{rung} child={child} has no clip"


def test_child_pool_wording_has_no_percentage_or_alarm_words():
    manifest = load_manifest()
    forbidden = ("%", "percent", "fault", "critical", "error", "battery", "temperature")
    for rung in Rung:
        for clip in (c for c in manifest.clips if c.id.startswith(line_id(rung, child=True) + ".")):
            text = clip.text.lower()
            assert not any(word in text for word in forbidden), clip.text
    texts = {c.text for c in manifest.clips if c.id.startswith("line.power.dock_child.")}
    assert "I'm sleepy, I need my charger." in texts
    adult = {c.text for c in manifest.clips if c.id.startswith("line.power.dock.")}
    assert "Could someone put me on my charger?" in adult


def test_no_em_dash_in_the_new_lines():
    raw = json.loads(MANIFEST_PATH.read_text())
    assert all(chr(0x2014) not in c["text"] for c in raw["clips"])


def test_child_pool_selection_never_reads_a_face():
    assert child_pool(None) is False
    assert child_pool([]) is False
    assert child_pool(["adult", "teen"]) is False
    assert child_pool(["adult", "child"]) is True
    assert child_pool(["unknown"]) is True


# ---- the run loop -----------------------------------------------------------------------


class _Bench:
    def __init__(self, **kwargs):
        self.battery = {"percent": 80, "charging": False}
        self.entries = [PresenceEntry("adult")]
        self.quiet = False
        self.now = 1000.0
        self.dim: list[bool] = []
        self.said: list[str] = []
        self.loop, self.parts = _make_loop(
            battery_status=lambda: dict(self.battery),
            presence_entries=lambda: self.entries,
            quiet_hours=lambda: self.quiet,
            sleep_clock=lambda: self.now,
            screen_dim=self.dim.append,
            **kwargs,
        )
        self.loop._say_clip = lambda clip_id, fallback=None: self.said.append(clip_id) or True

    def step(self, percent=None, charging=None, seconds=6.0):
        if percent is not None:
            self.battery["percent"] = percent
        if charging is not None:
            self.battery["charging"] = charging
        self.now += seconds
        self.loop._power_tick(False)  # starts the worker read when one is due
        self.loop._battery_status.wait_idle()
        self.loop._power_tick(False)  # and applies the answer it brought


def test_loop_ladder_on_a_scripted_discharge():
    bench = _Bench()
    for percent in (30, 21, 20, 19, 22, 20):
        bench.step(percent)
    assert bench.said == ["line.power.warn"]
    assert bench.dim == []
    bench.step(15)
    assert bench.dim == [True]
    assert bench.loop._suppression_context().low_power is True
    assert bench.said == ["line.power.warn"]  # degrade speaks nothing
    bench.step(10)
    assert bench.said[-1] == "line.power.dock"
    bench.step(9)
    bench.step(10)
    assert bench.said.count("line.power.dock") == 1


def test_loop_goodbye_grace_safe_pose_sleep_and_charging_wakes():
    bench = _Bench()
    bench.step(10)
    bench.step(5)
    assert bench.said[-1] == "line.power.goodbye"
    assert getattr(bench.loop._expression, "sleep_calls", []) == []
    bench.step(5, seconds=5.0)
    assert bench.loop._expression.sleep_calls == [True]
    assert bench.loop._power_asleep is True
    bench.step(4, seconds=60.0)  # asleep once per discharge
    assert bench.loop._expression.sleep_calls == [True]
    bench.step(6, charging=True)
    assert bench.loop._expression.sleep_calls == [True, False]
    assert bench.dim == [True, False]
    assert bench.loop._suppression_context().low_power is False


def test_loop_quiet_hours_silence_everything_but_the_goodbye():
    bench = _Bench()
    bench.quiet = True
    for percent in (20, 15, 10, 5):
        bench.step(percent)
    assert bench.said == ["line.power.goodbye"]


def test_loop_child_present_gets_the_child_pool():
    bench = _Bench()
    bench.entries = [PresenceEntry("adult"), PresenceEntry("child")]
    for percent in (20, 10, 5):
        bench.step(percent)
    assert bench.said == [
        "line.power.warn_child",
        "line.power.dock_child",
        "line.power.goodbye_child",
    ]


def test_loop_warn_is_silent_with_nobody_near_and_degrade_stops_head_moves():
    bench = _Bench()
    bench.entries = []
    bench.step(20)
    assert bench.said == []
    bench.step(15)
    assert bench.loop._power_motion_off() is True
    outcome = bench.loop._expression.render_primitive("breathe", bench.loop._suppression_context())
    assert outcome.suppressed_reason == "low_power"


def test_loop_reports_battery_level_charging_and_low_power_in_the_state_frame():
    bench = _Bench()
    bench.step(12)
    frame = bench.loop.snapshot()
    assert frame["battery_level"] == 12
    assert frame["charging"] is False
    assert frame["low_power"] is True
    assert frame["on_battery"] is True
    bench.step(30, charging=True)
    frame = bench.loop.snapshot()
    assert (frame["battery_level"], frame["charging"], frame["low_power"]) == (30, True, False)


def test_loop_without_a_battery_source_does_not_claim_one():
    loop, _ = _make_loop()
    assert "battery_level" not in loop.snapshot()
    assert "low_power" not in loop.snapshot()


def test_power_tick_without_a_source_or_owed_line_skips_policy_collaborators():
    def unexpected(*args, **kwargs):
        raise AssertionError("power policy collaborator called without an owed line")

    loop, _ = _make_loop(
        presence_entries=unexpected,
        quiet_hours=unexpected,
        sleep_clock=unexpected,
    )
    loop._is_muted = unexpected
    loop._current_funnel = unexpected
    loop._power_tick(False)


def test_loop_warn_at_follows_the_setting():
    bench = _Bench(power_warn_at=lambda: 30)
    bench.step(31)
    bench.step(30)
    assert bench.said == ["line.power.warn"]


class _Sampler:
    def __init__(self):
        self.temp = 50.0

    def read(self):
        return self.temp, False


def _hot_bench():
    sampler = _Sampler()
    monitor = ThermalMonitor(sampler, governor=ThermalGovernor(), interval_s=0.0)
    bench = _Bench(thermal=monitor)
    return bench, sampler


def _heat_step(bench, sampler, temp):
    sampler.temp = temp
    bench.loop._safety_ticks(False)
    bench.step(seconds=0.1)


def test_loop_critical_heat_stops_motion_and_says_one_line():
    bench, sampler = _hot_bench()
    for temp in (60.0, 70.0, 76.0):
        _heat_step(bench, sampler, temp)
        assert bench.loop._power_motion_off() is False
    _heat_step(bench, sampler, 82.0)
    assert bench.loop._power_motion_off() is True
    assert bench.said.count("line.power.heat") == 1  # the older warm line is separate
    outcome = bench.loop._expression.render_primitive("settle", bench.loop._suppression_context())
    assert outcome.suppressed_reason == "heat_stop"
    _heat_step(bench, sampler, 80.0)
    assert bench.loop._power_motion_off() is True
    _heat_step(bench, sampler, 78.0)
    assert bench.loop._power_motion_off() is False
    assert bench.said.count("line.power.heat") == 1


def test_loop_unknown_person_gets_the_child_pool_for_heat():
    bench, sampler = _hot_bench()
    bench.entries = [PresenceEntry("unknown")]
    _heat_step(bench, sampler, 83.0)
    assert [c for c in bench.said if c.startswith("line.power.")] == ["line.power.heat_child"]
