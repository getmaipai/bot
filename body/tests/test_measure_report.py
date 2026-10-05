"""The markdown a recorded run adds to docs/dev/measurements.md."""

from __future__ import annotations

from maipai_body.measure.report import (
    cue_motion_section,
    daemon_version_from,
    section_header_lines,
    stall_section,
)
from maipai_body.measure.run_header import new_run_header
from maipai_body.measure.stats import summarize

HEADER = new_run_header(
    row="M-R2", mode="sim", profile_id="reachy_mini", daemon_version="1.11.0", date="2026-10-05"
)


def test_section_header_lines_state_mode_daemon_profile_and_date_and_no_hostname():
    lines = "\n".join(section_header_lines(HEADER))
    assert "mode: `sim`" in lines
    assert "daemon version: `1.11.0`" in lines
    assert "profile: `reachy_mini`" in lines
    assert "image release: n/a" in lines
    assert "host" not in lines.lower()


def test_cue_motion_section_has_a_row_per_primitive_with_p50_and_p95():
    summary = {
        "primitive": "listen",
        "repeats": 3,
        "errors": 0,
        "no_onset": 0,
        "limits_exceeded_runs": 0,
        "commanded_peak_rad": 0.47,
        "cue_to_command_ms": summarize([0.1, 0.2, 0.3]),
        "cue_to_onset_ms": summarize([100.0, 110.0, 130.0]),
        "command_to_onset_ms": summarize([99.9, 109.8, 129.7]),
        "cue_to_settled_ms": summarize([900.0, 950.0, 1000.0]),
        "amplitude_rad": summarize([0.45, 0.46, 0.47]),
        "peak_velocity_rad_s": summarize([2.0, 2.5, 3.0]),
    }
    text = cue_motion_section(HEADER, [summary])
    assert text.startswith("## M-R2: cue to motion, repeated (sim), 2026-10-05\n")
    assert "| listen | 3 | 110.0 | 130.0 |" in text
    assert "| primitive |" in text


def test_a_primitive_with_no_onset_prints_n_a_never_zero():
    empty = summarize([])
    summary = {
        "primitive": "stop",
        "repeats": 2,
        "errors": 0,
        "no_onset": 2,
        "limits_exceeded_runs": 0,
        "commanded_peak_rad": 0.0,
        **{
            k: empty
            for k in (
                "cue_to_command_ms",
                "cue_to_onset_ms",
                "command_to_onset_ms",
                "cue_to_settled_ms",
                "amplitude_rad",
                "peak_velocity_rad_s",
            )
        },
    }
    text = cue_motion_section(HEADER, [summary])
    assert "| stop | 2 | n/a | n/a |" in text


def test_stall_section_marks_held_runs_and_their_verdicts():
    rows = [
        {
            "axis": "head_roll",
            "fraction": 0.1,
            "held": False,
            "commanded_rad": 0.1,
            "achieved_rad": 0.1,
            "verdict": "reached",
            "residual_rad": 0.0,
            "frames": 40,
        },
        {
            "axis": "head_roll",
            "fraction": 0.1,
            "held": True,
            "commanded_rad": 0.1,
            "achieved_rad": 0.0,
            "verdict": "stalled",
            "residual_rad": 0.0,
            "frames": 40,
        },
    ]
    text = stall_section(HEADER, rows)
    assert text.startswith("## M-R2: stall probe (sim), 2026-10-05\n")
    assert "| head_roll | 0.10 | no | " in text
    assert "| head_roll | 0.10 | yes | " in text
    assert "stalled" in text


def test_daemon_version_is_read_from_the_daemons_own_status_route():
    import http.server
    import json
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):  # noqa: N802
            body = json.dumps({"version": "9.9.9"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert daemon_version_from("127.0.0.1", server.server_port) == "9.9.9"
    finally:
        server.shutdown()


def test_link_loss_section_has_a_row_per_scenario_and_mode_and_a_wifi_table():
    from maipai_body.measure.report import link_loss_section

    header = new_run_header(
        row="M-R5", mode="sim", profile_id="reachy_mini", daemon_version="1.11.0", date="2026-10-05"
    )
    summary = {
        "scenario": "mid_turn",
        "mode": "reset",
        "trials": 4,
        "errors": 0,
        "cancel_ms": summarize([5.0, 6.0, 7.0, 9.0]),
        "pose_still_after_cancel_ms": summarize([0.0, 0.0, 33.0, 66.0]),
        "reconnect_ms": summarize([1000.0, 5000.0, 9000.0, 14000.0]),
        "max_cancels_per_turn": 1,
        "line_on_next_turn": 4,
        "line_on_turn_after": 0,
    }
    wifi = [
        {"outage_s": 20.0, "reachable_after_ms": 3400.0},
        {"outage_s": 20.0, "reachable_after_ms": None},
    ]
    text = link_loss_section(header, [summary], wifi_rows=wifi)
    assert text.startswith("## M-R5: the link (sim), 2026-10-05\n")
    assert "| mid_turn | reset | 4 | 6.0 | 9.0 |" in text
    assert "| 4/4 | 0/4 |" in text
    assert "| 20 | 3400.0 |" in text
    assert "| 20 | no answer |" in text


def test_link_loss_section_without_wifi_rows_has_no_wifi_table():
    from maipai_body.measure.report import link_loss_section

    header = new_run_header(row="M-R5", mode="sim", profile_id="p", daemon_version="1")
    assert "Wi-Fi" not in link_loss_section(header, [], wifi_rows=[])


def test_budget_section_reports_processes_temperature_throttle_turns_and_the_decision():
    from maipai_body.measure.report import budget_section

    header = new_run_header(
        row="M-R1",
        mode="unit",
        profile_id="reachy_mini",
        daemon_version="1.11.0",
        date="2026-10-05",
    )
    summary = {
        "samples": 720,
        "processes": {
            "daemon": {"samples": 720, "rss_mb_max": 310.5, "cpu_pct": summarize([10.0, 40.0])},
            "body": None,
        },
        "temp_c_max": 71.2,
        "mem_available_mb_min": 1200.0,
        "throttled": {"samples_throttled_now": 0, "ever_flagged_bits": 0},
        "turns": {
            "n": 30,
            "failed": 1,
            "endpoint_to_transcript_ms": summarize([800.0, 1100.0]),
            "turn_first_event_ms": summarize([300.0]),
            "tts_first_audio_ms": summarize([]),
        },
    }
    decision = {"adopt": False, "limit_ms": 1000.0, "reason": "p95 1100 ms is not under 1000 ms"}
    text = budget_section(header, "robot", summary, decision, duration_s=3600.0)
    assert text.startswith("## M-R1: the Compute Module budget, robot (unit), 2026-10-05\n")
    assert "| daemon | 310.5 |" in text
    assert "| body | not running |" in text
    assert "temperature max: 71.2 C" in text
    assert "throttled samples: 0" in text
    assert "endpoint to transcript p50 / p95: 800.0 / 1100.0 ms" in text
    assert "decision: robot tier not adopted (p95 1100 ms is not under 1000 ms)" in text


def test_budget_section_without_a_decision_says_so():
    from maipai_body.measure.report import budget_section

    header = new_run_header(row="M-R1", mode="unit", profile_id="p", daemon_version="1")
    summary = {
        "samples": 1,
        "processes": {},
        "temp_c_max": None,
        "mem_available_mb_min": None,
        "throttled": {"samples_throttled_now": 0, "ever_flagged_bits": 0},
        "turns": {"n": 0, "failed": 0},
    }
    text = budget_section(header, "daemon", summary, None, duration_s=60.0)
    assert "decision: not evaluated for this configuration" in text
    assert "temperature max: n/a" in text


def test_wake_doa_section_reports_whatever_parts_were_run_and_the_gates():
    from maipai_body.measure.report import wake_doa_section

    header = new_run_header(
        row="M-R3",
        mode="unit",
        profile_id="reachy_mini",
        daemon_version="1.11.0",
        date="2026-10-05",
    )
    parts = {
        "false_accepts": {"label": "tv at room level", "events": 1, "listened_hours": 2.5},
        "recall": [
            {"condition": "quiet_1m", "attempts": 10, "hits": 9},
            {"condition": "tv_3m", "attempts": 10, "hits": 8},
        ],
        "doa": [
            {
                "bearing_deg": 90.0,
                "expected_array_rad": 0.0,
                "readings": 60,
                "speech_readings": 50,
                "median_measured_rad": 0.1,
                "error_deg": summarize([4.0, 6.0, 9.0]),
            }
        ],
        "barge_in": {"attempts": 10, "hits": 7, "self_triggers": 0, "control_s": 60.0},
        "gates": {
            "false_accepts": {"pass": True, "gate": "g1", "value": "1 in 2.50 h"},
            "recall_quiet_1m": {"pass": True, "gate": "g2", "value": "9/10"},
            "recall_tv_3m": {"pass": None, "gate": "g3", "value": "3/3", "note": "few attempts"},
            "near_miss": {"pass": False, "gate": "g4", "value": "1 wakes"},
        },
    }
    text = wake_doa_section(header, parts)
    assert text.startswith("## M-R3: wake and direction of arrival (unit), 2026-10-05\n")
    assert "- false accepts: 1 in 2.50 h (tv at room level)" in text
    assert "| quiet_1m | 9/10 |" in text
    assert "| 90 | 0.000 | 0.100 | 50/60 | 6.0 | 9.0 |" in text
    assert "barge-in: 7/10 woke through playback; 0 self-triggers in 60 s of playback alone" in text
    assert "| false_accepts | pass |" in text
    assert "| recall_tv_3m | undecided |" in text
    assert "| near_miss | FAIL |" in text


def test_wake_doa_section_with_only_one_part_run_has_only_that_part():
    from maipai_body.measure.report import wake_doa_section

    header = new_run_header(row="M-R3", mode="unit", profile_id="p", daemon_version="1")
    text = wake_doa_section(
        header, {"recall": [{"condition": "quiet_1m", "attempts": 2, "hits": 2}]}
    )
    assert "| quiet_1m | 2/2 |" in text
    assert "bearing" not in text
    assert "barge-in" not in text


def test_battery_section_reports_what_the_probe_found_and_each_runs_clock():
    from maipai_body.measure.report import battery_section

    header = new_run_header(
        row="M-R4",
        mode="unit",
        profile_id="reachy_mini",
        daemon_version="1.11.0",
        date="2026-10-05",
    )
    probe = {
        "readable": False,
        "level_readable": False,
        "charger_readable": False,
        "power_supply": [],
        "daemon_facts": [],
        "daemon_paths": [],
        "unreachable_sources": [],
        "indirect": {
            "under_voltage_flags": {"under_voltage_now": False, "under_voltage_occurred": True}
        },
    }
    runs = [
        {
            "boot_id": "a",
            "workload": "idle",
            "charging": "no",
            "heartbeats": 400,
            "runtime_s": 11_880.0,
            "uncertainty_s": 30.0,
            "max_gap_s": 31.0,
            "gap_warning": False,
            "facts_seen": {},
        },
        {
            "boot_id": "b",
            "workload": "conversation",
            "charging": "yes",
            "heartbeats": 20,
            "runtime_s": 600.0,
            "uncertainty_s": 30.0,
            "max_gap_s": 900.0,
            "gap_warning": True,
            "facts_seen": {"BAT0.capacity": {"first": "100", "last": "97"}},
        },
    ]
    text = battery_section(header, probe, runs)
    assert text.startswith("## M-R4: battery (unit), 2026-10-05\n")
    assert "- readable battery or charger fact: none found" in text
    assert "under-voltage occurred: yes" in text
    assert "| idle | no | 3:18:00 | 30 | 400 | no |" in text
    assert "| conversation | yes | 0:10:00 | 30 | 20 | GAP |" in text
    assert "BAT0.capacity 100 to 97" in text


def test_battery_section_lists_the_facts_a_probe_did_find():
    from maipai_body.measure.report import battery_section

    header = new_run_header(row="M-R4", mode="unit", profile_id="p", daemon_version="1")
    probe = {
        "readable": True,
        "level_readable": True,
        "charger_readable": False,
        "power_supply": [{"name": "BAT0", "type": "Battery", "values": {"capacity": "88"}}],
        "daemon_facts": [
            {"source": "/api/daemon/status", "path": "power.battery_percent", "value": 80}
        ],
        "daemon_paths": ["/api/power/battery"],
        "unreachable_sources": [],
        "indirect": {"under_voltage_flags": None},
    }
    text = battery_section(header, probe, [])
    assert "- readable battery or charger fact: level" in text
    assert "BAT0 (Battery): capacity=88" in text
    assert "power.battery_percent = 80" in text
    assert "/api/power/battery" in text
    assert "under-voltage" in text and "unreadable" in text
