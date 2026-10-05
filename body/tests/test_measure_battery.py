"""M-R4: battery. Runtime by the clock from full to the LED's red, whether any
readable fact exists, whether it runs while charging.

The probe, the crash-safe log and the run analysis are proven here with
fakes; a discharging unit is the only thing that can fill them with numbers.
"""

from __future__ import annotations

import json
import os

import pytest

from maipai_body.measure.battery import (
    BOOT_ID_PATH,
    HeartbeatLog,
    _read_boot_id,
    analyze_runs,
    find_fact_keys,
    probe_battery_facts,
    read_heartbeats,
    run_battery,
    scan_power_supply,
)


def test_scan_power_supply_lists_each_supply_with_its_readable_files(tmp_path):
    battery = tmp_path / "BAT0"
    battery.mkdir()
    (battery / "type").write_text("Battery\n")
    (battery / "capacity").write_text("87\n")
    (battery / "voltage_now").write_text("6350000\n")
    (battery / "uevent").write_text("POWER_SUPPLY_NAME=BAT0\n")
    mains = tmp_path / "AC"
    mains.mkdir()
    (mains / "type").write_text("Mains\n")
    (mains / "online").write_text("1\n")

    found = {s["name"]: s for s in scan_power_supply(tmp_path)}
    assert found["BAT0"]["type"] == "Battery"
    assert found["BAT0"]["values"] == {"capacity": "87", "voltage_now": "6350000"}
    assert found["AC"]["values"] == {"online": "1"}


def test_scan_power_supply_of_a_missing_directory_is_empty_not_an_error(tmp_path):
    assert scan_power_supply(tmp_path / "nope") == []


def test_find_fact_keys_walks_nested_json_for_battery_shaped_names():
    status = {
        "state": "running",
        "backend_status": {"motor_control_mode": "enabled", "supply_voltage": 6.4},
        "power": {"battery_percent": 80, "charger_present": False},
        "temperature": 40,
    }
    hits = {path: value for path, value in find_fact_keys(status)}
    assert hits == {
        "backend_status.supply_voltage": 6.4,
        "power": {"battery_percent": 80, "charger_present": False},
        "power.battery_percent": 80,
        "power.charger_present": False,
    }


def test_find_fact_keys_finds_nothing_in_a_status_with_no_such_names():
    assert list(find_fact_keys({"state": "running", "temperature": 40, "mode": "x"})) == []


def _daemon(responses):
    def get(path):
        if path not in responses:
            raise OSError(path)
        return responses[path]

    return get


def test_probe_reports_no_readable_fact_when_nothing_battery_shaped_exists(tmp_path):
    probe = probe_battery_facts(
        daemon_get=_daemon(
            {
                "/api/daemon/status": {"state": "running"},
                "/api/state/full": {"head": 1},
                "/openapi.json": {"paths": {"/api/move/goto": {}, "/api/motors/status": {}}},
            }
        ),
        power_supply_root=tmp_path,
        run_command=lambda cmd: "throttled=0x0",
    )
    assert probe["readable"] is False
    assert probe["level_readable"] is False
    assert probe["charger_readable"] is False
    assert probe["power_supply"] == []
    assert probe["daemon_facts"] == []
    assert probe["daemon_paths"] == []
    assert probe["indirect"]["under_voltage_flags"] == {
        "under_voltage_now": False,
        "under_voltage_occurred": False,
    }


def test_probe_reports_a_readable_fact_found_in_the_daemons_own_status(tmp_path):
    probe = probe_battery_facts(
        daemon_get=_daemon(
            {
                "/api/daemon/status": {"power": {"battery_percent": 80}},
                "/api/state/full": {},
                "/openapi.json": {"paths": {"/api/power/battery": {}}},
            }
        ),
        power_supply_root=tmp_path,
        run_command=lambda cmd: "",
    )
    assert probe["readable"] is True
    assert {"source": "/api/daemon/status", "path": "power.battery_percent", "value": 80} in probe[
        "daemon_facts"
    ]
    assert probe["daemon_paths"] == ["/api/power/battery"]


def test_probe_tells_a_charger_flag_from_a_battery_level(tmp_path):
    """Design record section 12 names both as facts worth finding: "a voltage, a
    charger-present flag". A level lets the card say how full; a charger flag
    only lets it say "on battery". They are reported apart."""
    mains = tmp_path / "AC"
    mains.mkdir()
    (mains / "type").write_text("Mains\n")
    (mains / "online").write_text("1\n")
    only_mains = probe_battery_facts(
        daemon_get=_daemon({}), power_supply_root=tmp_path, run_command=lambda cmd: ""
    )
    assert only_mains["readable"] is True
    assert only_mains["charger_readable"] is True
    assert only_mains["level_readable"] is False

    battery = tmp_path / "BAT0"
    battery.mkdir()
    (battery / "type").write_text("Battery\n")
    (battery / "capacity").write_text("50\n")
    with_battery = probe_battery_facts(
        daemon_get=_daemon({}), power_supply_root=tmp_path, run_command=lambda cmd: ""
    )
    assert with_battery["level_readable"] is True


def test_every_heartbeat_is_flushed_and_fsynced_so_a_power_cut_keeps_it(tmp_path, monkeypatch):
    synced = []
    monkeypatch.setattr(os, "fsync", lambda fd: synced.append(fd))
    log = HeartbeatLog(tmp_path / "hb.jsonl", boot_id="boot-a", boot_clock=lambda: 12.5)
    log.append(workload="idle", extra={"temp_c": 40.0})
    log.append(workload="idle", extra={})
    assert len(synced) == 2
    lines = (tmp_path / "hb.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    assert first["seq"] == 0
    assert json.loads(lines[1])["seq"] == 1
    assert first["boot_id"] == "boot-a"
    assert first["t_boot_s"] == 12.5
    assert first["workload"] == "idle"
    assert first["temp_c"] == 40.0


def test_a_truncated_final_line_from_a_power_cut_is_dropped_not_fatal(tmp_path):
    path = tmp_path / "hb.jsonl"
    good = json.dumps({"seq": 0, "boot_id": "b", "t_boot_s": 1.0})
    path.write_text(good + "\n" + '{"seq": 1, "boot_id": "b", "t_b')
    assert [r["seq"] for r in read_heartbeats(path)] == [0]


def test_a_log_appended_to_across_boots_keeps_one_sequence_per_boot_id(tmp_path):
    path = tmp_path / "hb.jsonl"
    HeartbeatLog(path, boot_id="a", boot_clock=lambda: 1.0).append(workload="idle", extra={})
    HeartbeatLog(path, boot_id="b", boot_clock=lambda: 1.0).append(workload="idle", extra={})
    assert [r["boot_id"] for r in read_heartbeats(path)] == ["a", "b"]


def _beat(boot, t, workload="idle", **extra):
    return {"boot_id": boot, "t_boot_s": t, "workload": workload, **extra}


def test_runtime_is_the_span_of_one_boots_heartbeats_with_the_interval_as_its_uncertainty():
    records = [_beat("a", t) for t in (10.0, 40.0, 70.0, 100.0)]
    runs = analyze_runs(records, interval_s=30.0)
    assert len(runs) == 1
    assert runs[0]["runtime_s"] == pytest.approx(90.0)
    assert runs[0]["heartbeats"] == 4
    assert runs[0]["uncertainty_s"] == 30.0
    assert runs[0]["max_gap_s"] == pytest.approx(30.0)


def test_each_boot_is_its_own_run_and_a_run_names_its_workload():
    records = [
        _beat("a", 0.0, "idle"),
        _beat("a", 60.0, "idle"),
        _beat("b", 0.0, "conversation"),
        _beat("b", 30.0, "conversation"),
    ]
    runs = analyze_runs(records, interval_s=30.0)
    assert [r["workload"] for r in runs] == ["idle", "conversation"]
    assert [r["runtime_s"] for r in runs] == [60.0, 30.0]


def test_a_run_with_a_long_gap_flags_it_since_the_runtime_may_not_be_continuous():
    records = [_beat("a", 0.0), _beat("a", 30.0), _beat("a", 600.0)]
    runs = analyze_runs(records, interval_s=30.0)
    assert runs[0]["max_gap_s"] == pytest.approx(570.0)
    assert runs[0]["gap_warning"] is True


def test_a_runs_charging_note_and_tracked_fact_range_are_carried_through():
    records = [
        _beat("a", 0.0, charging="no", facts={"BAT0.capacity": "100"}),
        _beat("a", 30.0, charging="no", facts={"BAT0.capacity": "98"}),
    ]
    run = analyze_runs(records, interval_s=30.0)[0]
    assert run["charging"] == "no"
    assert run["facts_seen"] == {"BAT0.capacity": {"first": "100", "last": "98"}}


def test_run_battery_beats_on_the_interval_and_runs_the_workload_on_its_own_clock(tmp_path):
    now = [0.0]
    ticks: list[float] = []
    log = HeartbeatLog(tmp_path / "hb.jsonl", boot_id="a", boot_clock=lambda: now[0])
    run_battery(
        log,
        workload="conversation",
        duration_s=100.0,
        interval_s=30.0,
        work_interval_s=60.0,
        work=lambda: ticks.append(now[0]) or {"ok": True},
        read_facts=lambda: {"BAT0.capacity": "90"},
        clock=lambda: now[0],
        sleep=lambda s: now.__setitem__(0, now[0] + s),
    )
    beats = read_heartbeats(tmp_path / "hb.jsonl")
    assert [b["t_boot_s"] for b in beats] == [0.0, 30.0, 60.0, 90.0]
    assert ticks == [0.0, 60.0]
    assert beats[0]["facts"] == {"BAT0.capacity": "90"}
    assert beats[1]["turns_done"] == 1  # the first turn ran at t=0, and is counted by t=30


def test_a_work_item_that_raises_is_counted_not_fatal_to_the_heartbeat(tmp_path):
    now = [0.0]
    log = HeartbeatLog(tmp_path / "hb.jsonl", boot_id="a", boot_clock=lambda: now[0])

    def failing():
        raise RuntimeError("hub unreachable")

    run_battery(
        log,
        workload="conversation",
        duration_s=70.0,
        interval_s=30.0,
        work_interval_s=30.0,
        work=failing,
        read_facts=lambda: {},
        clock=lambda: now[0],
        sleep=lambda s: now.__setitem__(0, now[0] + s),
    )
    beats = read_heartbeats(tmp_path / "hb.jsonl")
    assert len(beats) == 3  # the beat never stopped
    assert beats[-1]["turns_failed"] >= 1


@pytest.mark.skipif(
    not BOOT_ID_PATH.exists(), reason=f"{BOOT_ID_PATH} is Linux-only; the unit runs Linux"
)
def test_the_log_defaults_to_the_kernels_boot_id_and_the_boot_clock(tmp_path):
    log = HeartbeatLog(tmp_path / "hb.jsonl")
    log.append(workload="idle", extra={})
    log.close()
    record = read_heartbeats(tmp_path / "hb.jsonl")[0]
    assert record["boot_id"] == BOOT_ID_PATH.read_text().strip()
    assert record["t_boot_s"] > 0.0


def test_without_a_kernel_boot_id_the_id_is_derived_from_the_boot_time(tmp_path):
    missing = tmp_path / "no_boot_id"
    # booted at wall 1000: any read during that boot gives the same id
    first = _read_boot_id(missing, boot_clock=lambda: 50.0, wall_clock=lambda: 1050.0)
    later = _read_boot_id(missing, boot_clock=lambda: 80.4, wall_clock=lambda: 1080.4)
    other_boot = _read_boot_id(missing, boot_clock=lambda: 5.0, wall_clock=lambda: 9005.0)
    assert first == later == "derived-1020"  # the boot time, rounded to the minute
    assert other_boot != first
    assert first.startswith("derived-")


def test_the_default_log_works_where_the_kernel_boot_id_is_absent(tmp_path, monkeypatch):
    import maipai_body.measure.battery as battery

    monkeypatch.setattr(battery, "BOOT_ID_PATH", tmp_path / "no_boot_id")
    log = HeartbeatLog(tmp_path / "hb.jsonl")
    log.append(workload="idle", extra={})
    log.close()
    record = read_heartbeats(tmp_path / "hb.jsonl")[0]
    assert record["boot_id"].startswith("derived-")
    assert record["t_boot_s"] > 0.0


def test_the_boot_clock_falls_back_to_the_monotonic_clock_where_the_os_has_no_boot_clock(
    monkeypatch,
):
    import time

    import maipai_body.measure.battery as battery

    monkeypatch.delattr(time, "CLOCK_BOOTTIME", raising=False)
    monkeypatch.delattr(time, "CLOCK_UPTIME_RAW", raising=False)
    monkeypatch.setattr(time, "monotonic", lambda: 42.0)
    assert battery._boot_clock() == 42.0
