"""MOTOR-RECOVER-01 and THERMAL-01 on the run loop: the presence tick drives the
motor watchdog and the thermal governor; neither can break the tick."""

from __future__ import annotations

from maipai_body.expression.suppression import suppression_reason
from maipai_body.presence.thermal import ThermalGovernor, ThermalMonitor
from tests.test_motion_state_hold import Bench


class _Health:
    def __init__(self, *, raises=False):
        self.ticks: list[bool] = []
        self.raises = raises

    def tick(self, *, held=False):
        self.ticks.append(held)
        if self.raises:
            raise RuntimeError("watchdog bug")

    def status(self):
        return {
            "motors_latched": ["head_1"],
            "motors_stuck": True,
            "motors_reboot_offer": ["head_1"],
        }

    def confirm_reboot(self, name, *, person_touching=False):
        return name == "head_1" and not person_touching

    def reboot_motors(self, names, *, person_touching=False):
        self.reboots = getattr(self, "reboots", [])
        self.reboots.append((list(names), person_touching))
        if person_touching:
            return {"rebooted": [], "failed": list(names)}
        ok = [n for n in names if n == "head_1"]
        return {"rebooted": ok, "failed": [n for n in names if n not in ok]}


def test_each_presence_tick_runs_the_watchdog_and_the_loop_reports_its_status():
    health = _Health()
    bench = Bench(motor_health=health)
    bench.tick(0.3)
    assert len(health.ticks) == 3 and not any(health.ticks)
    assert bench.loop.motor_status() == {
        "motors_latched": ["head_1"],
        "motors_stuck": True,
        "motors_reboot_offer": ["head_1"],
    }
    assert bench.loop.confirm_motor_reboot("head_1") is True


def test_a_held_body_tells_the_watchdog_it_is_held():
    health = _Health()
    bench = Bench(motor_health=health)
    bench.tick(1.5, shake=True)
    assert health.ticks[-1] is True


def test_a_failing_watchdog_never_breaks_the_presence_tick():
    bench = Bench(motor_health=_Health(raises=True))
    bench.tick(0.5)  # no exception
    assert bench.loop.state is not None


def test_the_state_frame_carries_the_reboot_offer():
    bench = Bench(motor_health=_Health())
    bench.tick(0.2)
    assert bench.loop.snapshot()["motors_reboot_offer"] == ["head_1"]


def test_a_motor_reboot_goes_to_the_watchdog_and_pushes_a_state_frame():
    health = _Health()
    bench = Bench(motor_health=health)
    bench.tick(0.3)
    assert bench.loop.reboot_motors(["head_1", "head_9"]) == {
        "rebooted": ["head_1"],
        "failed": ["head_9"],
    }
    assert health.reboots == [(["head_1", "head_9"], False)]


def test_a_motor_reboot_while_the_body_is_held_is_refused():
    health = _Health()
    bench = Bench(motor_health=health)
    bench.tick(1.5, shake=True)
    assert bench.loop.reboot_motors(["head_1"])["rebooted"] == []
    assert health.reboots[-1][1] is True


def test_with_no_watchdog_a_motor_reboot_fails_every_name():
    assert Bench().loop.reboot_motors(["head_1"]) == {"rebooted": [], "failed": ["head_1"]}


def test_with_no_watchdog_the_status_is_clean():
    bench = Bench()
    assert bench.loop.motor_status() == {
        "motors_latched": [],
        "motors_stuck": False,
        "motors_reboot_offer": [],
    }
    assert bench.loop.confirm_motor_reboot("head_1") is False


class _Sampler:
    def __init__(self, temp):
        self.temp = temp

    def read(self):
        return self.temp, False


def _warm_bench(temp, **kwargs):
    sampler = _Sampler(temp)
    monitor = ThermalMonitor(sampler, governor=ThermalGovernor(), interval_s=0.0)
    bench = Bench(thermal=monitor, **kwargs)
    return bench, sampler, monitor


def test_the_thermal_state_is_published_and_gates_the_idle_breathe():
    bench, sampler, _ = _warm_bench(65.0)
    bench.tick(0.2)
    assert bench.loop.thermal_state.level == 0
    assert bench.loop._suppression_context().thermal_pressure is False
    sampler.temp = 79.0
    bench.tick(0.2)
    assert bench.loop.thermal_state.idle_still is True
    assert bench.loop._suppression_context().thermal_pressure is True
    assert bench.loop.thermal_frame()["level"] == "idle_still"
    sampler.temp = 60.0
    bench.tick(0.2)
    assert bench.loop._suppression_context().thermal_pressure is False


def test_the_warm_line_is_said_once_per_episode_and_only_when_idle():
    said: list[str] = []
    bench, sampler, _ = _warm_bench(72.0)
    bench.loop._say_clip = lambda clip_id, fallback=None: said.append(clip_id) or True
    bench.tick(1.0)
    assert said == ["line.thermal"]
    sampler.temp = 80.0
    bench.tick(1.0)
    assert said == ["line.thermal"]


def test_the_warm_line_waits_for_a_free_moment_and_is_not_lost():
    said: list[str] = []
    bench, sampler, _ = _warm_bench(72.0)
    bench.loop._say_clip = lambda clip_id, fallback=None: said.append(clip_id) or True
    bench.loop._current_funnel = lambda: (
        __import__("maipai_body.run_loop", fromlist=["FunnelState"]).FunnelState.SPEAKING
    )
    bench.tick(0.5)
    assert said == []
    bench.loop._current_funnel = lambda: (
        __import__("maipai_body.run_loop", fromlist=["FunnelState"]).FunnelState.IDLE
    )
    bench.tick(0.5)
    assert said == ["line.thermal"]


def test_a_failing_thermal_sensor_never_breaks_the_presence_tick():
    class Boom:
        def poll(self):
            raise RuntimeError("sensor bug")

        def take_line(self):
            return False

    bench = Bench(thermal=Boom())
    bench.tick(0.5)
    assert bench.loop.thermal_state.level == 0


def test_the_loop_default_has_no_thermal_or_motor_hooks():
    bench = Bench()
    bench.tick(0.3)
    assert bench.loop.thermal_state.level == 0
    assert bench.loop.thermal_frame() is None


def test_a_stuck_motor_shows_the_error_look_and_clears_when_healthy():
    from tests.test_run_loop import _make_loop

    class Health:
        stuck = False

        def tick(self, *, held=False):
            pass

        def status(self):
            return {"motors_latched": [], "motors_stuck": self.stuck}

        def confirm_reboot(self, name, *, person_touching=False):
            return False

    health = Health()
    loop, _parts = _make_loop(motor_health=health)
    views = []
    loop.subscribe_view(views.append)
    loop._safety_ticks(False)
    assert views == []
    health.stuck = True
    loop._safety_ticks(False)
    loop._safety_ticks(False)
    assert [v.fault for v in views] == [True]
    health.stuck = False
    loop._safety_ticks(False)
    assert [v.fault for v in views] == [True, False]


# -- the state frame and the consumers (spec-v0.1.147) --


def test_the_state_frame_carries_motor_and_thermal_health_when_wired():
    bench, _, _ = _warm_bench(72.0, motor_health=_Health())
    bench.tick(0.2)
    frame = bench.loop.snapshot()
    assert frame["motors_latched"] == ["head_1"] and frame["motors_stuck"] is True
    assert frame["thermal"] == {
        "level": "vision_slowed",
        "temp_c": 72.0,
        "vision_hz": 2.0,
        "fault": False,
    }


def test_the_state_frame_omits_what_this_body_does_not_report():
    frame = Bench().loop.snapshot()
    assert "thermal" not in frame and "motors_latched" not in frame and "motors_stuck" not in frame


def test_the_state_frame_validates_against_the_pinned_spec_schema():
    import json
    import os
    from pathlib import Path

    import pytest

    spec = os.environ.get("MAIPAI_SPEC_DIR")
    jsonschema = pytest.importorskip("jsonschema")
    if not spec or not (Path(spec) / "schemas" / "robot-state.schema.json").exists():
        pytest.skip("pinned spec source not found (set MAIPAI_SPEC_DIR)")
    schema = json.loads((Path(spec) / "schemas" / "robot-state.schema.json").read_text())
    bench, _, _ = _warm_bench(79.0, motor_health=_Health())
    bench.tick(0.2)
    jsonschema.validate(bench.loop.snapshot(), schema)


def test_gestures_are_suspended_at_75_and_the_posture_cues_are_not():
    bench, sampler, _ = _warm_bench(65.0)
    bench.tick(0.2)
    assert suppression_reason("nod", bench.loop._suppression_context()) is None
    sampler.temp = 76.0
    bench.tick(0.2)
    context = bench.loop._suppression_context()
    assert context.thermal_gestures is True and context.thermal_pressure is False
    for gesture in ("nod", "perk", "shake", "offer", "thinking", "glance"):
        assert suppression_reason(gesture, context) == "thermal_gestures"
    assert suppression_reason("listen", context) is None
    assert suppression_reason("stop", context) is None
    sampler.temp = 60.0
    bench.tick(0.2)
    assert suppression_reason("nod", bench.loop._suppression_context()) is None


def test_a_react_move_waits_out_the_heat():
    played: list[str] = []
    bench, sampler, _ = _warm_bench(76.0)
    bench.loop._react_hook = lambda move, *_a, **_k: played.append(move) or True
    bench.tick(0.2)
    bench.loop._play_react("nod", True)
    assert played == []
    sampler.temp = 50.0
    bench.tick(0.2)
    bench.loop._play_react("nod", True)
    assert played == ["nod"]


def test_a_thermal_level_change_tells_the_reporter_at_once():
    changes: list[int] = []
    bench, sampler, _ = _warm_bench(60.0, on_change=lambda: changes.append(1))
    bench.tick(0.2)
    before = len(changes)
    sampler.temp = 71.0
    bench.tick(0.2)
    assert len(changes) > before


def test_a_new_reboot_offer_pushes_a_state_frame_once():
    from tests.test_run_loop import _make_loop

    class Health:
        offer: list[str] = []

        def tick(self, *, held=False):
            pass

        def status(self):
            return {
                "motors_latched": list(self.offer),
                "motors_stuck": bool(self.offer),
                "motors_reboot_offer": list(self.offer),
            }

    health = Health()
    changes = []
    loop, _parts = _make_loop(motor_health=health, on_change=lambda: changes.append(1))
    loop._safety_ticks(False)
    assert changes == []
    health.offer = ["stewart_3"]
    loop._safety_ticks(False)
    loop._safety_ticks(False)
    assert changes == [1]
    health.offer = []
    loop._safety_ticks(False)
    assert changes == [1, 1]
