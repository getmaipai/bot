"""M-R1 on the Compute Module: what the sampler reads, how it summarizes, and the
decision rule that picks the speech tier. Parsers and the loop are proven
here with injected readers; the real files and processes are the unit's.
"""

from __future__ import annotations

import pytest

from maipai_body.measure.budget import (
    BudgetSampler,
    decode_throttled,
    parse_meminfo,
    parse_thermal_millidegrees,
    parse_throttled,
    robot_tier_decision,
    run_budget,
    summarize_budget,
)


def test_throttled_bits_decode_to_named_flags():
    flags = decode_throttled(0x50005)
    assert flags["under_voltage_now"] is True
    assert flags["throttled_now"] is True
    assert flags["freq_capped_now"] is False
    assert flags["soft_temp_limit_now"] is False
    assert flags["under_voltage_occurred"] is True
    assert flags["throttled_occurred"] is True
    assert flags["freq_capped_occurred"] is False


def test_nothing_set_decodes_to_all_false():
    assert not any(decode_throttled(0).values())


def test_vcgencmd_output_parses_to_an_int_and_junk_to_none():
    assert parse_throttled("throttled=0x50005\n") == 0x50005
    assert parse_throttled("throttled=0x0") == 0
    assert parse_throttled("") is None
    assert parse_throttled("VCHI initialization failed") is None


def test_thermal_zone_reads_millidegrees_as_celsius():
    assert parse_thermal_millidegrees("48312\n") == pytest.approx(48.312)
    assert parse_thermal_millidegrees("garbage") is None


def test_meminfo_gives_total_and_available_in_megabytes():
    text = "MemTotal:        3969816 kB\nMemFree: 100 kB\nMemAvailable:    2048000 kB\n"
    assert parse_meminfo(text) == {"total_mb": pytest.approx(3877.0, abs=1), "available_mb": 2000.0}


class _Proc:
    def __init__(self, pid, cmdline, rss_bytes, cpu):
        self.pid, self._cmd, self._rss, self._cpu = pid, cmdline, rss_bytes, cpu

    def cmdline(self):
        return self._cmd

    def rss(self):
        return self._rss

    def cpu(self):
        return self._cpu


def _sampler(procs, throttled="throttled=0x0", temp="45000"):
    reads = {
        "/sys/class/thermal/thermal_zone0/temp": temp,
        "/proc/meminfo": "MemTotal: 4000000 kB\nMemAvailable: 2000000 kB\n",
    }
    return BudgetSampler(
        processes={"daemon": "reachy_mini.daemon", "body": "maipai_body"},
        list_processes=lambda: procs,
        read_text=lambda path: reads[path],
        run_command=lambda cmd: throttled,
    )


def test_a_sample_reports_rss_and_cpu_per_named_process_plus_system_facts():
    procs = [
        _Proc(10, ["python", "-m", "reachy_mini.daemon.app.main"], 300 * 2**20, 40.0),
        _Proc(11, ["python", "-m", "maipai_body"], 100 * 2**20, 12.5),
        _Proc(12, ["sshd"], 5 * 2**20, 0.0),
    ]
    sample = _sampler(procs).sample(t_s=5.0)
    assert sample["t_s"] == 5.0
    assert sample["processes"]["daemon"] == {"pids": [10], "rss_mb": 300.0, "cpu_pct": 40.0}
    assert sample["processes"]["body"]["rss_mb"] == 100.0
    assert "sshd" not in str(sample["processes"])
    assert sample["temp_c"] == 45.0
    assert sample["mem_available_mb"] == pytest.approx(1953.1, abs=0.5)
    assert sample["throttled_raw"] == 0
    assert sample["throttled_now"] is False


def test_a_missing_process_is_reported_absent_not_zero():
    sample = _sampler([_Proc(10, ["python", "reachy_mini.daemon"], 2**20, 1.0)]).sample(t_s=0.0)
    assert sample["processes"]["body"] is None


def test_unreadable_facts_are_none_never_a_made_up_number():
    sampler = BudgetSampler(
        processes={},
        list_processes=lambda: [],
        read_text=lambda path: (_ for _ in ()).throw(FileNotFoundError(path)),
        run_command=lambda cmd: (_ for _ in ()).throw(FileNotFoundError(cmd)),
    )
    sample = sampler.sample(t_s=0.0)
    assert sample["temp_c"] is None
    assert sample["throttled_raw"] is None
    assert sample["throttled_now"] is None
    assert sample["mem_available_mb"] is None


def test_run_budget_samples_on_the_interval_and_runs_a_turn_on_its_own_interval():
    now = [0.0]
    turns: list[float] = []

    def sleep(seconds):
        now[0] += seconds

    def turn():
        turns.append(now[0])
        return {"endpoint_to_transcript_ms": 400.0}

    sampler = _sampler([])
    samples, turn_rows = run_budget(
        sampler,
        duration_s=30.0,
        interval_s=5.0,
        turn_interval_s=10.0,
        run_turn=turn,
        clock=lambda: now[0],
        sleep=sleep,
    )
    assert [s["t_s"] for s in samples] == [0.0, 5.0, 10.0, 15.0, 20.0, 25.0]
    assert turns == [0.0, 10.0, 20.0]
    assert [r["endpoint_to_transcript_ms"] for r in turn_rows] == [400.0] * 3


def test_a_turn_that_raises_is_a_failed_turn_row_not_the_end_of_the_run():
    now = [0.0]

    def turn():
        raise RuntimeError("hub unreachable")

    samples, turn_rows = run_budget(
        _sampler([]),
        duration_s=10.0,
        interval_s=5.0,
        turn_interval_s=5.0,
        run_turn=turn,
        clock=lambda: now[0],
        sleep=lambda s: now.__setitem__(0, now[0] + s),
    )
    assert len(samples) == 2
    assert turn_rows[0]["error"] == "RuntimeError: hub unreachable"


def _samples(rss, cpu, temps, throttled_raws):
    return [
        {
            "t_s": float(i),
            "processes": {"daemon": {"pids": [1], "rss_mb": r, "cpu_pct": c}},
            "temp_c": t,
            "mem_available_mb": 1500.0 - r,
            "throttled_raw": raw,
            "throttled_now": bool(raw and raw & 0xF),
        }
        for i, (r, c, t, raw) in enumerate(zip(rss, cpu, temps, throttled_raws, strict=True))
    ]


def test_summary_reports_peak_rss_cpu_p95_peak_temperature_and_headroom():
    samples = _samples([100, 200, 300], [10, 20, 90], [40.0, 50.0, 60.0], [0, 0, 0])
    summary = summarize_budget(samples, [])
    assert summary["processes"]["daemon"]["rss_mb_max"] == 300.0
    assert summary["processes"]["daemon"]["cpu_pct"]["p95"] == 90.0
    assert summary["temp_c_max"] == 60.0
    assert summary["mem_available_mb_min"] == 1200.0
    assert summary["throttled"] == {"samples_throttled_now": 0, "ever_flagged_bits": 0}


def test_summary_counts_throttled_samples_and_ors_every_flag_ever_seen():
    samples = _samples([1, 1, 1], [1, 1, 1], [40.0] * 3, [0, 0x4, 0x40000])
    summary = summarize_budget(samples, [])
    assert summary["throttled"]["samples_throttled_now"] == 1
    assert summary["throttled"]["ever_flagged_bits"] == 0x40004


def test_summary_reports_turn_latency_percentiles_and_failures():
    turns = [
        {"endpoint_to_transcript_ms": 100.0},
        {"endpoint_to_transcript_ms": 300.0},
        {"error": "RuntimeError: x"},
    ]
    summary = summarize_budget([], turns)
    assert summary["turns"]["n"] == 3
    assert summary["turns"]["failed"] == 1
    assert summary["turns"]["endpoint_to_transcript_ms"]["p50"] == 100.0
    assert summary["turns"]["endpoint_to_transcript_ms"]["p95"] == 300.0


def test_the_robot_tier_is_adopted_only_under_m06_plus_500_ms_with_nothing_throttled():
    ok = robot_tier_decision(
        endpoint_to_transcript_p95_ms=900.0, m06_p95_ms=500.0, any_throttle=False, turns=30
    )
    assert ok["adopt"] is True
    over = robot_tier_decision(
        endpoint_to_transcript_p95_ms=1200.0, m06_p95_ms=500.0, any_throttle=False, turns=30
    )
    assert over["adopt"] is False
    assert "p95" in over["reason"]
    throttled = robot_tier_decision(
        endpoint_to_transcript_p95_ms=600.0, m06_p95_ms=500.0, any_throttle=True, turns=30
    )
    assert throttled["adopt"] is False
    assert "throttle" in throttled["reason"]


def test_the_boundary_is_not_adopted_because_the_rule_says_under():
    edge = robot_tier_decision(
        endpoint_to_transcript_p95_ms=1000.0, m06_p95_ms=500.0, any_throttle=False, turns=30
    )
    assert edge["adopt"] is False


def test_too_few_turns_is_inconclusive_never_adopt():
    few = robot_tier_decision(
        endpoint_to_transcript_p95_ms=100.0, m06_p95_ms=500.0, any_throttle=False, turns=5
    )
    assert few["adopt"] is False
    assert few["reason"].startswith("inconclusive")


def test_a_background_turn_does_not_stall_the_sampling_clock():
    import time

    def slow_turn():
        time.sleep(0.15)
        return {"endpoint_to_transcript_ms": 1.0}

    samples, turn_rows = run_budget(
        _sampler([]),
        duration_s=0.4,
        interval_s=0.05,
        turn_interval_s=0.1,
        run_turn=slow_turn,
        background_turns=True,
    )
    assert len(samples) >= 6  # a 0.15 s turn would have cost three of them inline
    assert len(turn_rows) >= 2


def test_a_turn_row_without_an_endpoint_is_left_out_of_the_percentiles_not_a_crash():
    turns = [{"endpoint_to_transcript_ms": None, "turn_total_ms": 5.0}]
    summary = summarize_budget([], turns)
    assert summary["turns"]["endpoint_to_transcript_ms"]["n"] == 0
    assert summary["turns"]["turn_total_ms"]["n"] == 1


def test_a_process_pattern_may_list_alternatives_separated_by_a_bar():
    procs = [_Proc(10, ["/venv/bin/python", "/venv/bin/reachy-mini-daemon"], 2**20, 1.0)]
    sampler = BudgetSampler(
        processes={"daemon": "reachy_mini.daemon|reachy-mini-daemon"},
        list_processes=lambda: procs,
        read_text=lambda path: "0",
        run_command=lambda cmd: "",
    )
    assert sampler.sample(t_s=0.0)["processes"]["daemon"]["pids"] == [10]


def test_the_real_lister_never_reports_the_measuring_process_itself():
    import os

    from maipai_body.measure.budget import psutil_lister

    assert os.getpid() not in [p.pid for p in psutil_lister()()]
