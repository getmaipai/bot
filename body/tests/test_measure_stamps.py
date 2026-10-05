"""S-EXPR-02: the motion onset stamps and their negative rows (dev.md section 5, Timing).

Deterministic: every clock is injected, so each row's numbers are exact.
"""

from __future__ import annotations

import numpy as np
import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient, LoopbackRecorder
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.measure.cue_motion import (
    loopback_acoustic_onset_ns,
    measure_primitive,
    stamp_reply_audio,
)
from maipai_body.measure.stamps import (
    COMMAND_P95_BUDGET_MS,
    SAFETY_SUPPRESSIONS,
    CueId,
    NullSink,
    StampRecorder,
    StampSink,
    summarize_rows,
)
from tests.kinematic_double import KinematicFakeClient

MS = 1_000_000
CUE = CueId("t1", 1)


def full_row(rec: StampRecorder, cue: CueId = CUE, *, base: int = 0, buffer_ms: int = 0) -> None:
    """One eligible row: heard, emitted 2 ms later, received 3 ms after that, and so on."""
    rec.stamp(cue, "t_heard", base)
    rec.stamp(cue, "t_cue_emitted", base + 2 * MS)
    rec.stamp(cue, "t_cue_received", base + 5 * MS)
    rec.stamp(cue, "t_motion_command", base + 7 * MS)
    rec.stamp(cue, "t_encoder_onset", base + 90 * MS)
    rec.stamp(cue, "t_first_audio_out", base + 40 * MS)
    rec.stamp(cue, "t_acoustic_onset", base + (40 + buffer_ms + 20) * MS)


def test_sinks_satisfy_the_protocol():
    assert isinstance(StampRecorder(), StampSink)
    assert isinstance(NullSink(), StampSink)


def test_null_sink_accepts_everything_and_keeps_nothing():
    sink = NullSink()
    sink.stamp(CUE, "t_heard", 1)
    sink.hub_stamp(CUE, "t_heard", 1)
    sink.suppressed(CUE, "near_hand", condition_present=True)
    sink.close_turn("t1", "done")
    sink.socket_lost()


def test_an_unknown_stamp_name_is_refused():
    with pytest.raises(ValueError, match="t_nonsense"):
        StampRecorder().stamp(CUE, "t_nonsense", 1)


def test_the_default_clock_is_monotonic_ns():
    ticks = iter([111, 222])
    rec = StampRecorder(clock=lambda: next(ticks))
    rec.stamp(CUE, "t_heard")
    rec.stamp(CUE, "t_cue_emitted")
    row = rec.rows()[0]
    assert (row.stamps["t_heard"], row.stamps["t_cue_emitted"]) == (111, 222)


def test_a_complete_row_derives_every_leg():
    rec = StampRecorder()
    full_row(rec)
    (row,) = rec.rows()
    assert row.status == "complete"
    assert row.socket_leg_ms == 3.0
    assert row.cue_to_command_ms == 2.0
    assert row.cue_to_onset_ms == 85.0
    assert row.cue_to_acoustic_ms == 55.0  # received at 5, acoustic at 60
    assert row.output_latency_ms == 20.0
    assert row.onset_before_acoustic is False  # encoder 90 ms, sound at 60 ms
    assert row.failure is not None  # the ordering rule: motion must precede the sound


def test_onset_before_the_acoustic_onset_passes():
    rec = StampRecorder()
    rec.stamp(CUE, "t_cue_received", 0)
    rec.stamp(CUE, "t_encoder_onset", 50 * MS)
    rec.stamp(CUE, "t_acoustic_onset", 80 * MS)
    (row,) = rec.rows()
    assert row.onset_before_acoustic is True
    assert row.failure is None


def test_a_row_with_no_acoustic_stamp_has_no_ordering_verdict():
    rec = StampRecorder()
    rec.stamp(CUE, "t_cue_received", 0)
    rec.stamp(CUE, "t_encoder_onset", 50 * MS)
    (row,) = rec.rows()
    assert row.onset_before_acoustic is None
    assert row.failure is None


def test_a_stamp_is_first_wins_and_a_repeat_is_counted():
    rec = StampRecorder()
    rec.stamp(CUE, "t_cue_received", 10)
    rec.stamp(CUE, "t_cue_received", 99)
    (row,) = rec.rows()
    assert row.stamps["t_cue_received"] == 10
    assert row.duplicates == 1


# -- the negative rows --


def test_a_dropped_cue_is_a_dropped_row_not_a_zero_latency():
    rec = StampRecorder()
    rec.stamp(CUE, "t_cue_emitted", 0)  # never received
    full_row(rec, CueId("t1", 2), base=100 * MS)
    rows = {r.cue_id: r for r in rec.rows()}
    assert rows[CUE].status == "dropped"
    assert rows[CUE].socket_leg_ms is None
    summary = summarize_rows(rec.rows())
    assert summary["dropped"] == 1
    assert summary["socket_leg_ms"]["n"] == 1  # the dropped row is not in the percentiles


def test_a_duplicated_cue_moves_the_head_once_and_is_counted():
    rec = StampRecorder()
    full_row(rec)
    rec.stamp(CUE, "t_cue_received", 500 * MS)  # the same cue id again
    rec.stamp(CUE, "t_motion_command", 501 * MS)
    (row,) = rec.rows()
    assert row.stamps["t_cue_received"] == 5 * MS
    assert row.stamps["t_motion_command"] == 7 * MS
    assert row.duplicates == 2
    assert summarize_rows(rec.rows())["duplicates"] == 2


def test_a_cue_after_done_is_dropped_and_counted_and_never_stamps_a_command():
    rec = StampRecorder()
    full_row(rec)
    rec.close_turn("t1", "done")
    late = CueId("t1", 2)
    rec.stamp(late, "t_cue_emitted", 300 * MS)
    rec.stamp(late, "t_cue_received", 303 * MS)
    rec.stamp(late, "t_motion_command", 304 * MS)
    rows = {r.cue_id: r for r in rec.rows()}
    assert rows[late].status == "late"
    assert "t_motion_command" not in rows[late].stamps
    assert rows[late].failure is not None  # a late cue that moved the head is a failure
    assert summarize_rows(rec.rows())["late"] == 1


def test_a_cue_already_open_when_its_turn_closes_still_finishes_its_row():
    rec = StampRecorder()
    rec.stamp(CUE, "t_cue_received", 0)
    rec.close_turn("t1", "cancel")
    rec.stamp(CUE, "t_motion_command", 1 * MS)
    (row,) = rec.rows()
    assert row.status == "complete"
    assert row.stamps["t_motion_command"] == 1 * MS


def test_a_deep_playback_buffer_is_judged_against_the_acoustic_onset():
    shallow, deep = StampRecorder(), StampRecorder()
    full_row(shallow, buffer_ms=0)
    full_row(deep, buffer_ms=200)
    (s,), (d,) = shallow.rows(), deep.rows()
    # first audio out is at 40 ms in both; only the acoustic onset moved
    assert s.output_latency_ms == 20.0
    assert d.output_latency_ms == 220.0
    assert s.onset_before_acoustic is False
    assert d.onset_before_acoustic is True  # encoder 90 ms < sound at 260 ms
    assert d.failure is None
    summary = summarize_rows(deep.rows())
    assert summary["output_latency_ms"]["p50"] == 220.0  # recorded, per bench


def test_a_socket_loss_marks_unreceived_cues_and_clears_old_ids():
    rec = StampRecorder()
    rec.stamp(CUE, "t_cue_emitted", 0)
    got = CueId("t1", 2)
    rec.stamp(got, "t_cue_emitted", 1 * MS)
    rec.stamp(got, "t_cue_received", 2 * MS)
    rec.socket_lost()
    rec.stamp(CUE, "t_cue_received", 50 * MS)  # arrives after the loss: old id, dropped
    rows = {r.cue_id: r for r in rec.rows()}
    assert rows[CUE].status == "socket_lost"
    assert "t_cue_received" not in rows[CUE].stamps
    assert rows[got].status == "complete"
    summary = summarize_rows(rec.rows())
    assert summary["socket_lost"] == 1
    assert summary["late"] == 0  # a loss is its own count, not a late cue


def test_a_hub_stamp_is_recorded_but_never_orders_anything():
    plain, with_hub = StampRecorder(), StampRecorder()
    full_row(plain)
    full_row(with_hub)
    # the hub's clock is somewhere else entirely, and says the cue came before the wake
    with_hub.hub_stamp(CUE, "t_heard", 9_000_000_000_000)
    with_hub.hub_stamp(CUE, "t_cue_emitted", 1)
    (a,), (b,) = plain.rows(), with_hub.rows()
    assert b.hub == {"t_heard": 9_000_000_000_000, "t_cue_emitted": 1}
    assert b.hub_disagrees is True
    assert a.hub_disagrees is None
    for name in ("socket_leg_ms", "cue_to_command_ms", "cue_to_onset_ms", "cue_to_acoustic_ms"):
        assert getattr(a, name) == getattr(b, name)
    assert a.stamps == b.stamps
    assert summarize_rows(with_hub.rows())["hub_disagreements"] == 1


def test_a_hub_interval_that_matches_the_local_one_agrees_despite_another_clock():
    rec = StampRecorder()
    full_row(rec)  # local heard to emitted: 2 ms
    offset = 7_000_000_000_000
    rec.hub_stamp(CUE, "t_heard", offset)
    rec.hub_stamp(CUE, "t_cue_emitted", offset + 2 * MS)
    (row,) = rec.rows()
    assert row.hub_disagrees is False


# -- suppression --


@pytest.mark.parametrize("reason", sorted(SAFETY_SUPPRESSIONS))
def test_a_safety_suppression_with_its_condition_present_passes(reason):
    rec = StampRecorder()
    rec.stamp(CUE, "t_cue_received", 0)
    rec.suppressed(CUE, reason, condition_present=True)
    (row,) = rec.rows()
    assert row.status == "suppressed"
    assert row.failure is None


def test_a_safety_reason_whose_condition_was_absent_fails():
    rec = StampRecorder()
    rec.stamp(CUE, "t_cue_received", 0)
    rec.suppressed(CUE, "near_hand", condition_present=False)
    assert "condition" in rec.rows()[0].failure


@pytest.mark.parametrize("reason", ["", "unexplained", "playfulness_forbidden"])
def test_an_unlisted_suppression_fails(reason):
    rec = StampRecorder()
    rec.stamp(CUE, "t_cue_received", 0)
    rec.suppressed(CUE, reason, condition_present=True)
    assert rec.rows()[0].failure is not None


# -- the summary --


def test_the_summary_reports_p50_and_p95_and_the_command_budget_verdict():
    rec = StampRecorder()
    for n in range(20):
        cue = CueId("t", n)
        rec.stamp(cue, "t_cue_received", 0)
        rec.stamp(cue, "t_motion_command", (n + 1) * MS)
    summary = summarize_rows(rec.rows())
    cmd = summary["cue_to_command_ms"]
    assert (cmd["p50"], cmd["p95"], cmd["n"]) == (10.0, 19.0, 20)
    assert summary["command_within_budget"] is True
    assert COMMAND_P95_BUDGET_MS == 50.0


def test_a_p95_over_budget_is_reported_as_over():
    rec = StampRecorder()
    for n, ms in enumerate([1, 1, 1, 80]):
        cue = CueId("t", n)
        rec.stamp(cue, "t_cue_received", 0)
        rec.stamp(cue, "t_motion_command", ms * MS)
    assert summarize_rows(rec.rows())["command_within_budget"] is False


def test_no_rows_give_no_numbers_and_no_verdict():
    summary = summarize_rows([])
    assert summary["cue_to_command_ms"]["p50"] is None
    assert summary["command_within_budget"] is None


# -- through the harness and the fake's loopback recorder --


def test_measure_primitive_stamps_received_command_and_encoder_onset():
    rec = StampRecorder()
    client = KinematicFakeClient(REACHY_MINI_PROFILE)
    row = measure_primitive(
        client,
        REACHY_MINI_PROFILE,
        "perk",
        sink=rec,
        cue_id=CUE,
        neutral_duration_s=0.0,
        pause_s=0.05,
        window_s=0.45,
    )
    (stamped,) = rec.rows()
    assert {"t_cue_received", "t_motion_command", "t_encoder_onset"} <= set(stamped.stamps)
    assert stamped.cue_to_command_ms == pytest.approx(row["cue_to_command_ms"], abs=0.001)
    assert stamped.cue_to_onset_ms == pytest.approx(row["cue_to_onset_ms"], abs=0.001)


def test_measure_primitive_without_a_sink_is_unchanged():
    client = KinematicFakeClient(REACHY_MINI_PROFILE)
    row = measure_primitive(
        client, REACHY_MINI_PROFILE, "perk", neutral_duration_s=0.0, pause_s=0.05, window_s=0.3
    )
    assert row["cue_to_onset_ms"] is not None


def _loopback_client(ticks_s):
    it = iter(ticks_s)
    recorder = LoopbackRecorder(clock=lambda: next(it))
    return FakeReachyMiniClient(recorder=recorder), recorder


def test_the_loopback_gives_the_acoustic_onset_and_the_first_audio_stamp():
    client, recorder = _loopback_client([2.0])  # one push, at 2.0 s on the recorder clock
    rec = StampRecorder()
    tone = np.full(160, 0.5, dtype=np.float32)
    stamp_reply_audio(client, rec, CUE, tone, clock=lambda: 1_990_000_000)
    stamped = rec.rows()[0]
    assert stamped.stamps["t_first_audio_out"] == 1_990_000_000
    assert loopback_acoustic_onset_ns(recorder) == 2_000_000_000
    assert recorder.events == ["start", "push"]


def test_the_acoustic_onset_skips_leading_silence_and_adds_the_device_latency():
    client, recorder = _loopback_client([1.0, 1.5])
    client.start_playing()
    client.push_audio_sample(np.zeros(160, dtype=np.float32))
    client.push_audio_sample(np.full(160, 0.4, dtype=np.float32))
    assert loopback_acoustic_onset_ns(recorder) == 1_500_000_000
    assert loopback_acoustic_onset_ns(recorder, output_latency_ns=200 * MS) == 1_700_000_000


def test_a_silent_loopback_has_no_acoustic_onset():
    client, recorder = _loopback_client([1.0])
    client.start_playing()
    client.push_audio_sample(np.zeros(160, dtype=np.float32))
    assert loopback_acoustic_onset_ns(recorder) is None
