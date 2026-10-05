"""M-R2, sim-first: cue to first state-feed delta per primitive, repeated for
p50 and p95, amplitude against the declared limits, and the stall probe.

Runs on a command-driven kinematic double always, and against the
simulator's real daemon when ``MAIPAI_BODY_LIVE=1`` (the same gate as
``conftest.py``'s ``body_client``): the same assertions, two benches.
"""

from __future__ import annotations

import os

import pytest

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.primitives import PRIMITIVE_NAMES
from maipai_body.expression.reachy_mini_renderer import build_steps
from maipai_body.hal.seam import HeadPose
from maipai_body.measure.cue_motion import (
    StampingClient,
    measure_primitive,
    measure_repeated,
    measure_stall_probe,
)
from maipai_body.measure.motion import commanded_peak_rad
from tests.conftest import LIVE_HOST, LIVE_PORT, _live_daemon_reachable
from tests.kinematic_double import KinematicFakeClient

# Fast pacing for the double; the live bench runs at the script's real pacing.
FAST = {"neutral_duration_s": 0.0, "pause_s": 0.05, "window_s": 0.45}
LIVE = {"neutral_duration_s": 0.8, "pause_s": 0.3, "window_s": 1.5}

MOVING = [p for p in PRIMITIVE_NAMES if p not in ("settle", "stop")]


@pytest.fixture(params=["kinematic", "live"])
def bench(request):
    if request.param == "kinematic":
        yield KinematicFakeClient(REACHY_MINI_PROFILE), FAST
        return
    if os.environ.get("MAIPAI_BODY_LIVE") != "1":
        pytest.skip("MAIPAI_BODY_LIVE is not set to 1")
    if not _live_daemon_reachable():
        pytest.skip(f"no daemon answering on {LIVE_HOST}:{LIVE_PORT}")
    client = ReachyMiniClient(REACHY_MINI_PROFILE, host=LIVE_HOST, port=LIVE_PORT)
    yield client, LIVE
    client.disconnect()


def test_stamping_client_records_when_the_first_command_reaches_the_seam():
    inner = KinematicFakeClient(REACHY_MINI_PROFILE)
    ticks = iter([100, 200, 300])
    client = StampingClient(inner, clock=lambda: next(ticks))
    assert client.t_first_command_ns is None
    client.goto(pose=HeadPose(yaw=0.1), duration_s=0.1)
    client.set_target(pose=HeadPose(yaw=0.2))
    assert client.t_first_command_ns == 100  # the first command, not the last
    assert [c.kind for c in inner.sent_commands] == ["goto", "set_target"]
    client.reset()
    assert client.t_first_command_ns is None


def test_stamping_client_still_refuses_commands_after_a_loss():
    from maipai_body.hal.errors import BodyLost

    inner = KinematicFakeClient(REACHY_MINI_PROFILE)
    inner.simulate_disconnect()
    client = StampingClient(inner)
    with pytest.raises(BodyLost):
        client.hold()


def test_a_moving_primitive_has_a_cue_to_command_to_onset_split(bench):
    client, pacing = bench
    row = measure_primitive(client, REACHY_MINI_PROFILE, "listen", **pacing)
    assert row["cue_to_onset_ms"] is not None
    assert row["cue_to_command_ms"] is not None
    assert 0.0 <= row["cue_to_command_ms"] <= row["cue_to_onset_ms"]
    assert row["command_to_onset_ms"] == pytest.approx(
        row["cue_to_onset_ms"] - row["cue_to_command_ms"], abs=0.01
    )


@pytest.mark.parametrize("primitive", PRIMITIVE_NAMES)
def test_every_primitive_stays_inside_the_declared_limits(bench, primitive):
    client, pacing = bench
    row = measure_primitive(client, REACHY_MINI_PROFILE, primitive, **pacing)
    assert row["limits_exceeded"] == []
    assert row["amplitude_rad"] <= row["commanded_peak_rad"] + 0.05
    if primitive in MOVING:
        assert row["cue_to_onset_ms"] is not None, f"{primitive} never moved"


def test_stop_commands_no_motion_so_it_has_nothing_to_stall(bench):
    client, pacing = bench
    row = measure_primitive(client, REACHY_MINI_PROFILE, "stop", **pacing)
    assert row["commanded_peak_rad"] == commanded_peak_rad(build_steps("stop", REACHY_MINI_PROFILE))
    assert row["stall"] == "no_motion_commanded"


def test_repeated_runs_report_p50_and_p95_of_each_latency():
    client = KinematicFakeClient(REACHY_MINI_PROFILE)
    summary = measure_repeated(client, REACHY_MINI_PROFILE, "perk", repeats=4, **FAST)
    assert summary["primitive"] == "perk"
    assert summary["repeats"] == 4
    onset = summary["cue_to_onset_ms"]
    assert onset["n"] == 4
    assert onset["p50"] <= onset["p95"]
    assert summary["amplitude_rad"]["n"] == 4
    assert summary["errors"] == 0


def test_a_repeat_that_captures_no_frames_is_counted_as_an_error_not_averaged_in():
    client = KinematicFakeClient(REACHY_MINI_PROFILE)
    client.state_feed = lambda frequency=30.0: iter(())  # a feed that yields nothing
    summary = measure_repeated(client, REACHY_MINI_PROFILE, "perk", repeats=2, **FAST)
    assert summary["errors"] == 2
    assert summary["cue_to_onset_ms"]["n"] == 0


def test_the_stall_probe_reaches_every_fraction_on_a_free_head():
    client = KinematicFakeClient(REACHY_MINI_PROFILE)
    rows = measure_stall_probe(
        client, REACHY_MINI_PROFILE, axis="head_roll", fractions=(0.1, 0.2), **FAST
    )
    assert [r["fraction"] for r in rows] == [0.1, 0.2]
    assert all(r["verdict"] == "reached" for r in rows)
    assert rows[1]["commanded_rad"] > rows[0]["commanded_rad"]
    assert all(r["held"] is False for r in rows)


def test_the_stall_probe_reports_stalled_when_the_head_is_held_still():
    client = KinematicFakeClient(REACHY_MINI_PROFILE, held=True)
    rows = measure_stall_probe(
        client, REACHY_MINI_PROFILE, axis="head_roll", fractions=(0.1, 0.2), held=True, **FAST
    )
    assert all(r["verdict"] == "stalled" for r in rows)
    assert all(r["achieved_rad"] < 0.01 for r in rows)
    assert all(r["held"] is True for r in rows)


def test_the_stall_probe_asks_the_operator_before_each_held_run_and_lets_go_after():
    client = KinematicFakeClient(REACHY_MINI_PROFILE, held=True)
    asked: list[str] = []
    measure_stall_probe(
        client,
        REACHY_MINI_PROFILE,
        axis="head_pitch",
        fractions=(0.05, 0.1),
        held=True,
        confirm=lambda message: asked.append(message),
        **FAST,
    )
    assert len(asked) == 2
    assert "head_pitch" in asked[0]
    assert client.sent_commands[-1].kind == "goto"  # last act: back to neutral
    assert client.sent_commands[-1].pose == HeadPose()


def test_the_stall_probe_returns_to_neutral_even_if_a_run_raises():
    client = KinematicFakeClient(REACHY_MINI_PROFILE)

    def _refuse(message: str) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        measure_stall_probe(
            client,
            REACHY_MINI_PROFILE,
            axis="head_pitch",
            fractions=(0.05,),
            held=True,
            confirm=_refuse,
            **FAST,
        )
    assert client.sent_commands[-1].pose == HeadPose()


def test_the_mr2_runner_returns_cue_motion_summaries_and_stall_rows():
    from maipai_body.measure.cue_motion import run_mr2

    client = KinematicFakeClient(REACHY_MINI_PROFILE)
    result = run_mr2(
        client,
        REACHY_MINI_PROFILE,
        repeats=2,
        primitives=["listen", "stop"],
        stall_axes=["head_roll"],
        stall_fractions=(0.1,),
        held=False,
        **FAST,
    )
    assert [s["primitive"] for s in result["cue_motion"]] == ["listen", "stop"]
    assert [r["axis"] for r in result["stall"]] == ["head_roll"]


def test_the_mr2_runner_can_skip_the_stall_probe():
    from maipai_body.measure.cue_motion import run_mr2

    client = KinematicFakeClient(REACHY_MINI_PROFILE)
    result = run_mr2(
        client,
        REACHY_MINI_PROFILE,
        repeats=1,
        primitives=["perk"],
        stall_axes=[],
        stall_fractions=(),
        held=False,
        **FAST,
    )
    assert result["stall"] == []


def test_the_stall_probe_residual_is_read_after_the_head_has_been_sent_back():
    client = KinematicFakeClient(REACHY_MINI_PROFILE)
    rows = measure_stall_probe(
        client,
        REACHY_MINI_PROFILE,
        axis="head_roll",
        fractions=(0.3,),
        neutral_duration_s=0.0,
        pause_s=0.3,
        window_s=0.45,
    )
    assert rows[0]["achieved_rad"] > 0.1  # it did move out
    assert rows[0]["residual_rad"] < 0.02  # and the residual is measured after it came back
