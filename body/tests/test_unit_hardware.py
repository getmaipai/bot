"""The measurement rows' unit-ready checks: what has to hold on the physical Reachy Mini
before an hour-long run is worth starting. Skipped without the device.

Run on the unit, with the daemon running and the body app stopped::

    MAIPAI_UNIT=1 uv run pytest tests/test_unit_hardware.py -q

``MAIPAI_UNIT=1`` is not enough on its own: the daemon on port 8000 must also
report it is not a simulator, so the deterministic CI and a dev laptop's
simulator skip these with a reason and never fail. (``MAIPAI_UNIT_ALLOW_SIM=1``
lifts the simulator check, for developing these tests only; expect the
hardware reads to fail there.) Each test names the measurement row it guards.
"""

from __future__ import annotations

import os

import pytest
import requests

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.measure.battery import probe_battery_facts
from maipai_body.measure.budget import BudgetSampler, psutil_lister
from maipai_body.measure.cue_motion import measure_primitive, measure_stall_probe
from maipai_body.speech.capture import AudioCapture
from tests.conftest import LIVE_HOST, LIVE_PORT, _live_daemon_reachable

pytestmark = pytest.mark.unit_only


def _skip_reason() -> str | None:
    if os.environ.get("MAIPAI_UNIT") != "1":
        return "MAIPAI_UNIT is not set to 1"
    if not _live_daemon_reachable():
        return f"no daemon answering on {LIVE_HOST}:{LIVE_PORT}"
    if os.environ.get("MAIPAI_UNIT_ALLOW_SIM") == "1":
        return None
    status = requests.get(f"http://{LIVE_HOST}:{LIVE_PORT}/api/daemon/status", timeout=5).json()
    if status.get("simulation_enabled"):
        return "the daemon is a simulator, not the unit"
    return None


@pytest.fixture(scope="module")
def unit():
    reason = _skip_reason()
    if reason is not None:
        pytest.skip(reason)
    client = ReachyMiniClient(REACHY_MINI_PROFILE, host=LIVE_HOST, port=LIVE_PORT)
    yield client
    client.disconnect()


def test_m_r1_the_sampler_reads_the_real_daemon_temperature_and_throttle_flags(unit):
    sampler = BudgetSampler(
        processes={"daemon": "reachy_mini.daemon|reachy-mini-daemon"},
        list_processes=psutil_lister(),
    )
    sampler.sample(t_s=0.0)  # primes the CPU counters
    sample = sampler.sample(t_s=1.0)
    assert sample["processes"]["daemon"] is not None, "the daemon process was not found"
    assert sample["processes"]["daemon"]["rss_mb"] > 0.0
    assert sample["temp_c"] is not None, "no thermal zone readable"
    assert sample["throttled_raw"] is not None, "vcgencmd get_throttled unreadable"


def test_m_r2_a_cue_moves_the_real_head_inside_the_declared_limits(unit):
    row = measure_primitive(unit, REACHY_MINI_PROFILE, "listen")
    assert row["cue_to_onset_ms"] is not None, "the head never moved"
    assert row["limits_exceeded"] == []
    assert row["amplitude_rad"] <= row["commanded_peak_rad"] + 0.05


def test_m_r2_the_smallest_stall_fraction_is_reached_on_a_free_head(unit):
    rows = measure_stall_probe(unit, REACHY_MINI_PROFILE, axis="head_roll", fractions=(0.05,))
    assert rows[0]["verdict"] == "reached"


def test_m_r3_the_array_answers_with_an_angle_inside_its_documented_range(unit):
    reading = unit.get_doa()
    assert reading is not None, "the microphone array answered nothing"
    assert 0.0 <= reading.angle_rad <= 3.15  # 0 left, pi right (the SDK's own convention)


def test_m_r3_the_daemons_audio_path_delivers_capture_blocks(unit):
    import time

    capture = AudioCapture(unit)
    capture.start()
    try:
        deadline = time.monotonic() + 3.0
        blocks = []
        while not blocks and time.monotonic() < deadline:
            blocks = capture.poll_blocks()
            time.sleep(0.05)
    finally:
        capture.stop()
    assert blocks, "no audio blocks within 3 s"


def test_m_r4_the_battery_probe_runs_on_the_unit_and_returns_its_answer(unit):
    from maipai_body.measure.battery import daemon_getter

    probe = probe_battery_facts(daemon_get=daemon_getter(f"http://{LIVE_HOST}:{LIVE_PORT}"))
    assert set(probe) >= {"readable", "level_readable", "charger_readable", "power_supply"}
    # The answer itself (readable or not) is the measurement; this only proves it was asked.


def test_m_r5_a_lost_hub_mid_turn_cancels_once_and_the_real_head_settles(unit):
    from maipai_body.measure.link_loss import LinkLossBench, run_trial
    from maipai_body.measure.stand_in_hub import StandInHub

    with StandInHub() as hub:
        bench = LinkLossBench(unit, REACHY_MINI_PROFILE, hub, report_interval_s=1.0)
        bench.start()
        try:
            row = run_trial(
                bench, "mid_turn", "reset", cancel_timeout_s=10.0, recover_timeout_s=10.0
            )
        finally:
            bench.stop()
    assert row["cancels"] == 1
    assert row["pose_still_after_cancel_ms"] is not None


def test_link_state_rung_0_cues_move_the_real_head_and_fold_the_antennas_away(unit):
    """LINK-STATE-01 rung 0 on the real body: link lost settles and breathes,
    the away pose folds both antennas back, a redeem stirs. Injected clock, so
    it takes seconds, not minutes. Needs the unit; skipped everywhere else."""
    from maipai_body.expression.engine import ExpressionEngine
    from maipai_body.expression.suppression import SuppressionContext
    from maipai_body.link.rung0 import Rung0Cues, Rung0Settings
    from maipai_body.link.state_machine import LinkStateMachine
    from tests.ladder_fakes import FakeClock

    clock = FakeClock()
    machine = LinkStateMachine(clock=clock, wall_clock=clock.wall_clock, sleep_after_s=600.0)
    engine = ExpressionEngine(unit, REACHY_MINI_PROFILE)
    cues = Rung0Cues(
        machine=machine,
        clock=clock,
        render=lambda p: engine.render_ambient(p, SuppressionContext()).rendered,
        settings=Rung0Settings(away_after_s=10.0, tracking_off_after_s=20.0),
    )
    machine.link_lost("unit check")
    cues.tick()  # settle, breathe
    clock.advance(10.0)
    cues.tick()  # the away pose
    feed = unit.state_feed(frequency=10.0)
    try:
        frame = next(iter(feed))
    finally:
        feed.close()
    assert frame.antennas is not None
    assert frame.antennas.left < -0.05 and frame.antennas.right < -0.05, frame.antennas
    machine.redeemed("lan", None)
    cues.tick()  # the stir, then the settle
    assert machine.phase.value == "connected"
