"""M-R3: wake and direction of arrival on this array. The scoring, the bearing maths
and the gates are proven here against scripted audio; the real array, the real
model and a person speaking are the unit's."""

from __future__ import annotations

import math

import numpy as np
import pytest

from maipai_body.hal.seam import DirectionOfArrival
from maipai_body.measure.wake_doa import (
    collect_doa,
    count_false_accepts,
    eight_bearings,
    evaluate_wake_gates,
    expected_array_angle,
    listen_for_wake,
    play_samples,
    summarize_bearing,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_eight_bearings_are_forty_five_degrees_apart_starting_straight_ahead():
    bearings = eight_bearings()
    assert len(bearings) == 8
    assert bearings[0] == 0.0
    assert bearings[1] == pytest.approx(math.pi / 4)
    assert bearings[-1] == pytest.approx(7 * math.pi / 4)


@pytest.mark.parametrize(
    ("bearing_deg", "expected_rad"),
    [
        (0, math.pi / 2),  # straight ahead: the array's front/back angle
        (90, 0.0),  # the robot's left: 0 rad is left in the SDK's own words
        (-90, math.pi),  # its right: pi rad is right
        (45, math.pi / 4),
        (135, math.pi / 4),  # behind-left reads the same as ahead-left
        (180, math.pi / 2),  # straight behind reads the same as straight ahead
        (225, 3 * math.pi / 4),
        (315, 3 * math.pi / 4),
    ],
)
def test_expected_array_angle_follows_the_sdk_convention_with_front_back_folded(
    bearing_deg, expected_rad
):
    assert expected_array_angle(math.radians(bearing_deg)) == pytest.approx(expected_rad)


def _readings(angles, speech=True):
    return [DirectionOfArrival(angle_rad=a, speech_detected=speech) for a in angles]


def test_a_bearing_summary_reports_error_in_degrees_over_speech_readings_only():
    bearing = math.radians(90)  # expected array angle 0
    readings = _readings([0.05, 0.10, 0.20]) + _readings([2.0], speech=False)
    summary = summarize_bearing(readings, bearing)
    assert summary["readings"] == 4
    assert summary["speech_readings"] == 3
    assert summary["error_deg"]["p50"] == pytest.approx(math.degrees(0.10))
    assert summary["error_deg"]["p95"] == pytest.approx(math.degrees(0.20))
    assert summary["median_measured_rad"] == pytest.approx(0.10)


def test_a_bearing_with_no_speech_readings_has_no_error_figure_not_a_zero():
    summary = summarize_bearing(_readings([1.0], speech=False), 0.0)
    assert summary["speech_readings"] == 0
    assert summary["error_deg"]["n"] == 0
    assert summary["median_measured_rad"] is None


def test_collect_doa_polls_the_array_for_the_dwell_and_keeps_every_reading():
    clock = _Clock()
    values = iter([DirectionOfArrival(angle_rad=0.1 * i, speech_detected=True) for i in range(100)])

    class Audio:
        def get_doa(self):
            return next(values)

    readings = collect_doa(Audio(), dwell_s=1.0, hz=10.0, sleep=clock.sleep)
    assert len(readings) == 10


def test_collect_doa_skips_polls_the_array_could_not_answer():
    clock = _Clock()
    answers = iter([None, DirectionOfArrival(angle_rad=0.2, speech_detected=True), None])

    class Audio:
        def get_doa(self):
            return next(answers, None)

    readings = collect_doa(Audio(), dwell_s=0.3, hz=10.0, sleep=clock.sleep)
    assert [r.angle_rad for r in readings] == [0.2]


class _Capture:
    def __init__(self, clock: _Clock, step_s: float = 0.05) -> None:
        self._clock, self._step = clock, step_s

    def poll_blocks(self):
        self._clock.sleep(self._step)
        return [np.zeros(512, dtype=np.float32)]


class _Scorer:
    """Fires on the polls named in ``fire_at`` (1-based) and tracks the last score."""

    def __init__(self, fire_at, scores=None):
        self.fire_at = set(fire_at)
        self.calls = 0
        self.last_score = 0.0
        self._scores = scores or {}

    def poll(self, block):
        self.calls += 1
        self.last_score = self._scores.get(self.calls, 0.0)
        if self.calls in self.fire_at:
            self.last_score = max(self.last_score, 0.9)
            return object()
        return None


def test_listen_for_wake_reports_a_hit_with_its_delay_and_best_score():
    clock = _Clock()
    scorer = _Scorer({4}, scores={2: 0.3})
    result = listen_for_wake(_Capture(clock), scorer, window_s=2.0, clock=clock, sleep=clock.sleep)
    assert result["fired"] is True
    assert result["delay_s"] == pytest.approx(0.2)
    assert result["best_score"] == pytest.approx(0.9)


def test_listen_for_wake_reports_a_miss_after_the_window_with_the_best_score_seen():
    clock = _Clock()
    scorer = _Scorer(set(), scores={3: 0.6})
    result = listen_for_wake(_Capture(clock), scorer, window_s=1.0, clock=clock, sleep=clock.sleep)
    assert result["fired"] is False
    assert result["delay_s"] is None
    assert result["best_score"] == pytest.approx(0.6)


def test_count_false_accepts_lists_when_each_one_fired_and_the_listening_duration():
    clock = _Clock()
    scorer = _Scorer({10, 30})
    result = count_false_accepts(
        _Capture(clock), scorer, duration_s=2.0, clock=clock, sleep=clock.sleep
    )
    assert result["events_s"] == [pytest.approx(0.5), pytest.approx(1.5)]
    assert result["duration_s"] == pytest.approx(2.0, abs=0.06)


def test_gates_are_undecidable_on_short_runs_and_say_so():
    gates = evaluate_wake_gates(
        false_accepts=0,
        listened_hours=0.5,
        recall_quiet_1m=(10, 10),
        recall_tv_3m=(8, 10),
        near_miss=(0, 10),
    )
    assert gates["false_accepts"]["pass"] is None
    assert "2 hours" in gates["false_accepts"]["note"]
    assert gates["recall_quiet_1m"]["pass"] is True
    assert gates["recall_tv_3m"]["pass"] is True
    assert gates["near_miss"]["pass"] is True


def test_gates_fail_below_nine_in_ten_quiet_and_eight_in_ten_with_the_television_on():
    gates = evaluate_wake_gates(
        false_accepts=1,
        listened_hours=2.0,
        recall_quiet_1m=(8, 10),
        recall_tv_3m=(7, 10),
        near_miss=(1, 10),
    )
    assert gates["false_accepts"]["pass"] is True  # one in two hours is the limit, not over it
    assert gates["recall_quiet_1m"]["pass"] is False
    assert gates["recall_tv_3m"]["pass"] is False
    assert gates["near_miss"]["pass"] is False


def test_two_false_accepts_in_two_hours_fail_the_gate():
    gates = evaluate_wake_gates(
        false_accepts=2,
        listened_hours=2.0,
        recall_quiet_1m=(10, 10),
        recall_tv_3m=(10, 10),
        near_miss=(0, 10),
    )
    assert gates["false_accepts"]["pass"] is False


def test_recall_with_fewer_than_ten_attempts_is_undecidable():
    gates = evaluate_wake_gates(
        false_accepts=0,
        listened_hours=3.0,
        recall_quiet_1m=(3, 3),
        recall_tv_3m=(10, 10),
        near_miss=(0, 10),
    )
    assert gates["recall_quiet_1m"]["pass"] is None


def test_play_samples_pushes_in_paced_chunks_and_stops_when_asked():
    import threading

    clock = _Clock()
    pushed: list[int] = []

    class Playback:
        def push(self, chunk):
            pushed.append(len(chunk))

    stop = threading.Event()
    samples = np.zeros(16000, dtype=np.float32)  # one second at 16 kHz
    play_samples(Playback(), samples, 16000, chunk_s=0.25, stop=stop, sleep=clock.sleep)
    assert pushed == [4000] * 4
    assert clock.now == pytest.approx(1.0)

    pushed.clear()
    stop.set()
    play_samples(Playback(), samples, 16000, chunk_s=0.25, stop=stop, sleep=clock.sleep)
    assert pushed == []


def test_assemble_parts_gathers_the_part_files_into_the_report_shape_with_gates():
    from maipai_body.measure.wake_doa import assemble_parts

    rows = [
        {"part": "false_accepts", "label": "tv", "events": 1, "listened_hours": 2.5},
        {"part": "recall", "condition": "quiet_1m", "attempts": 10, "hits": 9},
        {"part": "recall", "condition": "tv_3m", "attempts": 10, "hits": 8},
        {"part": "recall", "condition": "near_miss", "attempts": 10, "hits": 0},
        {"part": "doa", "bearings": [{"bearing_deg": 0.0}]},
        {"part": "barge_in", "attempts": 10, "hits": 7, "self_triggers": 0, "control_s": 60.0},
    ]
    parts = assemble_parts(rows)
    assert parts["false_accepts"]["events"] == 1
    assert [r["condition"] for r in parts["recall"]] == ["quiet_1m", "tv_3m", "near_miss"]
    assert parts["doa"] == [{"bearing_deg": 0.0}]
    assert parts["barge_in"]["hits"] == 7
    assert parts["gates"]["false_accepts"]["pass"] is True
    assert parts["gates"]["recall_quiet_1m"]["pass"] is True
    assert parts["gates"]["near_miss"]["pass"] is True


def test_assemble_parts_with_a_part_not_run_leaves_its_gate_undecided_not_failed():
    from maipai_body.measure.wake_doa import assemble_parts

    parts = assemble_parts(
        [{"part": "recall", "condition": "quiet_1m", "attempts": 10, "hits": 10}]
    )
    assert parts["gates"]["false_accepts"]["pass"] is None
    assert parts["gates"]["recall_tv_3m"]["pass"] is None
    assert parts["gates"]["recall_quiet_1m"]["pass"] is True
    assert parts["gates"]["near_miss"]["pass"] is None  # never run is never a pass
    assert "doa" not in parts


def test_assemble_parts_of_nothing_is_an_error():
    from maipai_body.measure.wake_doa import assemble_parts

    with pytest.raises(ValueError):
        assemble_parts([])
