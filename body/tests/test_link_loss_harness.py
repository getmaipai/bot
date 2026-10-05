"""M-R5 on the bench: the trial harness against a stand-in hub whose link it cuts.

Same harness the simulator and the unit run (``scripts/measure_mr5_link.py``);
here the body behind the seam is the kinematic double, so what is proven is
the harness and the loop's behaviour, not the daemon's.
"""

from __future__ import annotations

import pytest

from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.measure.link_loss import LinkLossBench, run_trial, summarize_trials
from maipai_body.measure.stand_in_hub import StandInHub
from tests.kinematic_double import KinematicFakeClient


@pytest.fixture
def bench():
    with StandInHub(tts_seconds=0.4) as hub:
        running = LinkLossBench(
            KinematicFakeClient(REACHY_MINI_PROFILE),
            REACHY_MINI_PROFILE,
            hub,
            report_interval_s=0.4,
        )
        running.start()
        try:
            yield running
        finally:
            running.stop()


def _trial(bench, scenario):
    return run_trial(
        bench, scenario, "reset", cancel_timeout_s=5.0, settle_window_s=0.4, recover_timeout_s=5.0
    )


@pytest.mark.parametrize(
    ("scenario", "phases"),
    [
        ("listening", ["heard", "cancel"]),
        ("mid_turn", ["heard", "signal", "cancel"]),
        ("mid_sentence", ["heard", "signal", "speak", "cancel"]),
    ],
)
def test_a_reset_is_one_cancel_a_settled_pose_a_reconnect_and_one_line(bench, scenario, phases):
    row = run_trial(
        bench, scenario, "reset", cancel_timeout_s=5.0, settle_window_s=0.3, recover_timeout_s=5.0
    )
    # one cancel, in the right place in the turn, never a done after it
    assert row["phases"] == phases
    assert row["cancels"] == 1
    # a reset is noticed at once, and the head is still after the stop
    assert row["cancel_ms"] is not None
    assert 0.0 <= row["cancel_ms"] < 1500.0
    assert row["pose_still_after_cancel_ms"] is not None
    # back on the next state report: not before the link, not later than one interval plus a poll
    assert row["reconnect_ms"] is not None
    assert 0.0 <= row["reconnect_ms"] < 400.0 + 1500.0
    # the lost turn is announced once, on the next turn, and not the one after
    assert row["line_on_next_turn"] is True
    assert row["line_on_turn_after"] is False


def test_trials_summarize_to_p50_and_p95_per_figure():
    def row(cancel, reconnect, line):
        return {
            "cancel_ms": cancel,
            "pose_still_after_cancel_ms": 5.0,
            "reconnect_ms": reconnect,
            "cancels": 1,
            "line_on_next_turn": line,
            "line_on_turn_after": False,
        }

    summary = summarize_trials(
        [row(10.0, 100.0, True), row(30.0, 300.0, True), {"error": "no cancel within 1 s"}]
    )
    assert summary["trials"] == 3
    assert summary["errors"] == 1
    assert summary["cancel_ms"] == {"n": 2, "p50": 10.0, "p95": 30.0, "min": 10.0, "max": 30.0}
    assert summary["reconnect_ms"]["p95"] == 300.0
    assert summary["max_cancels_per_turn"] == 1
    assert summary["line_on_next_turn"] == 2
    assert summary["line_on_turn_after"] == 0


def test_a_trial_that_never_cancels_is_an_error_row_not_a_number(bench):
    row = run_trial(
        bench,
        "mid_turn",
        "blackhole",
        cancel_timeout_s=0.3,  # far shorter than the client's own read timeout
        settle_window_s=0.1,
        recover_timeout_s=3.0,
    )
    assert row["cancel_ms"] is None
    assert row["error"] == "no cancel within 0.3 s"


def test_the_link_stays_down_for_the_outage_so_the_reconnect_is_read_at_a_known_phase(bench):
    row = run_trial(
        bench,
        "mid_turn",
        "reset",
        cancel_timeout_s=5.0,
        settle_window_s=0.2,
        recover_timeout_s=5.0,
        outage_s=1.2,
    )
    assert row["outage_s"] == 1.2
    assert bench.hub.restored_at - bench.hub.loss_at >= 1.2
    # up for less than one 0.4 s interval after the outage, whatever phase it fell in
    assert 0.0 <= row["reconnect_ms"] < 400.0 + 1500.0


def test_stratified_outages_cover_the_report_interval_evenly():
    from maipai_body.measure.link_loss import stratified_outages

    assert stratified_outages(4, interval_s=8.0) == [1.0, 3.0, 5.0, 7.0]
    assert stratified_outages(1, interval_s=15.0) == [7.5]
    assert stratified_outages(0, interval_s=15.0) == []
