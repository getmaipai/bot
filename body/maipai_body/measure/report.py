"""Markdown sections for ``docs/dev/measurements.md``, one per recorded run."""

from __future__ import annotations

from typing import Any

import requests


def daemon_version_from(host: str, port: int, *, timeout_s: float = 5.0) -> str:
    """The daemon's own reported version (``/api/daemon/status``)."""
    response = requests.get(f"http://{host}:{port}/api/daemon/status", timeout=timeout_s)
    response.raise_for_status()
    return str(response.json()["version"])


def section_header_lines(header: dict[str, Any]) -> list[str]:
    """The bullet list dev.md section 11 asks every run to open with."""
    sim_note = "Pollen's MuJoCo daemon, `--sim`" if header["mode"] == "sim" else "the physical unit"
    return [
        f"- mode: `{header['mode']}` ({sim_note})",
        f"- daemon version: `{header['daemon_version']}`",
        f"- image release: {header['image_release'] or 'n/a'}",
        f"- profile: `{header['profile']}`",
    ]


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def _rad(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def cue_motion_section(header: dict[str, Any], summaries: list[dict[str, Any]]) -> str:
    lines = [
        f"## M-R2: cue to motion, repeated ({header['mode']}), {header['date']}",
        "",
        *section_header_lines(header),
        "- onset threshold and settle rule: `maipai_body/measure/motion.py`",
        "",
        "| primitive | runs | onset p50 (ms) | onset p95 (ms) | cue→command p50 (ms) | "
        "command→onset p50 (ms) | settled p50 (ms) | amplitude p50 (rad) | "
        "peak velocity p95 (rad/s) | commanded peak (rad) | no onset | errors | over limit |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        lines.append(
            f"| {s['primitive']} | {s['repeats']} | {_ms(s['cue_to_onset_ms']['p50'])} | "
            f"{_ms(s['cue_to_onset_ms']['p95'])} | {_ms(s['cue_to_command_ms']['p50'])} | "
            f"{_ms(s['command_to_onset_ms']['p50'])} | {_ms(s['cue_to_settled_ms']['p50'])} | "
            f"{_rad(s['amplitude_rad']['p50'])} | {_rad(s['peak_velocity_rad_s']['p95'])} | "
            f"{_rad(s['commanded_peak_rad'])} | {s['no_onset']} | {s['errors']} | "
            f"{s['limits_exceeded_runs']} |"
        )
    lines.append("")
    return "\n".join(lines)


def stall_section(header: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        f"## M-R2: stall probe ({header['mode']}), {header['date']}",
        "",
        *section_header_lines(header),
        "- fraction: share of the axis's declared limit commanded by one `goto`",
        "",
        "| axis | fraction | held | commanded (rad) | achieved (rad) | verdict | "
        "residual after release (rad) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['axis']} | {r['fraction']:.2f} | | error: {r['error']} | | | |")
            continue
        lines.append(
            f"| {r['axis']} | {r['fraction']:.2f} | {'yes' if r['held'] else 'no'} | "
            f"{_rad(r['commanded_rad'])} | {_rad(r['achieved_rad'])} | {r['verdict']} | "
            f"{_rad(r['residual_rad'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def link_loss_section(
    header: dict[str, Any], summaries: list[dict[str, Any]], *, wifi_rows: list[dict[str, Any]]
) -> str:
    lines = [
        f"## M-R5: the link ({header['mode']}), {header['date']}",
        "",
        *section_header_lines(header),
        "- cancel: from the link going down to the CANCEL cue reaching the expression engine",
        "- still: from the cancel to the first run of still frames in the state feed",
        "- reconnect: from the link returning to the next successful state report",
        "- line: the lost turn announced once on the next turn, and not on the one after",
        "",
        "| scenario | fault | trials | cancel p50 (ms) | cancel p95 (ms) | still p50 (ms) | "
        "still p95 (ms) | reconnect p50 (ms) | reconnect p95 (ms) | max cancels per turn | "
        "line next | line after | errors |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        trials = s["trials"]
        lines.append(
            f"| {s['scenario']} | {s['mode']} | {trials} | {_ms(s['cancel_ms']['p50'])} | "
            f"{_ms(s['cancel_ms']['p95'])} | {_ms(s['pose_still_after_cancel_ms']['p50'])} | "
            f"{_ms(s['pose_still_after_cancel_ms']['p95'])} | {_ms(s['reconnect_ms']['p50'])} | "
            f"{_ms(s['reconnect_ms']['p95'])} | {s['max_cancels_per_turn']} | "
            f"{s['line_on_next_turn']}/{trials} | {s['line_on_turn_after']}/{trials} | "
            f"{s['errors']} |"
        )
    if wifi_rows:
        lines += [
            "",
            "Wi-Fi cycled on the unit (radio off for the outage, then on):",
            "",
            "| outage (s) | hub reachable after radio on (ms) |",
            "|---|---|",
        ]
        for r in wifi_rows:
            reached = (
                "no answer" if r["reachable_after_ms"] is None else _ms(r["reachable_after_ms"])
            )
            lines.append(f"| {r['outage_s']:g} | {reached} |")
    lines.append("")
    return "\n".join(lines)


def _pair(summary: dict[str, Any], unit: str = "ms") -> str:
    if summary.get("p50") is None:
        return "n/a"
    return f"{summary['p50']:.1f} / {summary['p95']:.1f} {unit}"


def budget_section(
    header: dict[str, Any],
    config: str,
    summary: dict[str, Any],
    decision: dict[str, Any] | None,
    *,
    duration_s: float,
) -> str:
    temp = summary["temp_c_max"]
    available = summary["mem_available_mb_min"]
    turns = summary["turns"]
    lines = [
        f"## M-R1: the Compute Module budget, {config} ({header['mode']}), {header['date']}",
        "",
        *section_header_lines(header),
        f"- run: {summary['samples']} samples over {duration_s:g} s; {turns['n']} turns "
        f"({turns['failed']} failed)",
        "",
        "| process | RSS max (MB) | CPU p50 / p95 (%) |",
        "|---|---|---|",
    ]
    for name, figures in summary["processes"].items():
        if not figures or figures["rss_mb_max"] is None:
            lines.append(f"| {name} | not running | |")
        else:
            lines.append(
                f"| {name} | {figures['rss_mb_max']:.1f} | {_pair(figures['cpu_pct'], '')} |"
            )
    lines += [
        "",
        f"- temperature max: {'n/a' if temp is None else f'{temp:.1f} C'}",
        f"- memory available, minimum: {'n/a' if available is None else f'{available:.0f} MB'}",
        f"- throttled samples: {summary['throttled']['samples_throttled_now']}; flags ever "
        f"set: {summary['throttled']['ever_flagged_bits']:#x}",
    ]
    for key, label in (
        ("endpoint_to_transcript_ms", "endpoint to transcript"),
        ("turn_first_event_ms", "turn first event"),
        ("tts_first_audio_ms", "tts first audio"),
    ):
        if key in turns:
            lines.append(f"- {label} p50 / p95: {_pair(turns[key])}")
    if decision is None:
        lines.append("- decision: not evaluated for this configuration")
    else:
        verdict = "adopted" if decision["adopt"] else "not adopted"
        lines.append(f"- decision: robot tier {verdict} ({decision['reason']})")
    lines.append("")
    return "\n".join(lines)


def wake_doa_section(header: dict[str, Any], parts: dict[str, Any]) -> str:
    lines = [
        f"## M-R3: wake and direction of arrival ({header['mode']}), {header['date']}",
        "",
        *section_header_lines(header),
        "- gates: `docs/dev.md` section 11 (M-08's)",
    ]
    if "false_accepts" in parts:
        fa = parts["false_accepts"]
        lines.append(
            f"- false accepts: {fa['events']} in {fa['listened_hours']:.2f} h ({fa['label']})"
        )
    if "barge_in" in parts:
        b = parts["barge_in"]
        lines.append(
            f"- barge-in: {b['hits']}/{b['attempts']} woke through playback; "
            f"{b['self_triggers']} self-triggers in {b['control_s']:g} s of playback alone"
        )
    if parts.get("recall"):
        lines += ["", "| condition | woke |", "|---|---|"]
        for r in parts["recall"]:
            lines.append(f"| {r['condition']} | {r['hits']}/{r['attempts']} |")
    if parts.get("doa"):
        lines += [
            "",
            "Array angle: 0 rad is the robot's left, pi/2 front or back, pi right; error is "
            "taken in array-angle space.",
            "",
            "| bearing (deg) | expected (rad) | median measured (rad) | speech readings | "
            "error p50 (deg) | error p95 (deg) |",
            "|---|---|---|---|---|---|",
        ]
        for d in parts["doa"]:
            median = (
                "n/a" if d["median_measured_rad"] is None else f"{d['median_measured_rad']:.3f}"
            )
            p50, p95 = d["error_deg"]["p50"], d["error_deg"]["p95"]
            lines.append(
                f"| {d['bearing_deg']:g} | {d['expected_array_rad']:.3f} | {median} | "
                f"{d['speech_readings']}/{d['readings']} | "
                f"{'n/a' if p50 is None else f'{p50:.1f}'} | "
                f"{'n/a' if p95 is None else f'{p95:.1f}'} |"
            )
    if parts.get("gates"):
        lines += ["", "| gate | result | value | rule |", "|---|---|---|---|"]
        for name, gate in parts["gates"].items():
            result = {True: "pass", False: "FAIL", None: "undecided"}[gate["pass"]]
            lines.append(f"| {name} | {result} | {gate['value']} | {gate['gate']} |")
    lines.append("")
    return "\n".join(lines)


def _hms(seconds: float) -> str:
    whole = int(round(seconds))
    return f"{whole // 3600}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


def battery_section(
    header: dict[str, Any], probe: dict[str, Any] | None, runs: list[dict[str, Any]]
) -> str:
    lines = [
        f"## M-R4: battery ({header['mode']}), {header['date']}",
        "",
        *section_header_lines(header),
    ]
    if probe is not None:
        kinds = [
            k
            for k, found in (
                ("level", probe["level_readable"]),
                ("charger", probe["charger_readable"]),
            )
            if found
        ]
        lines.append(
            f"- readable battery or charger fact: {', '.join(kinds) if kinds else 'none found'}"
        )
        flags = probe["indirect"]["under_voltage_flags"]
        if flags is None:
            lines.append("- under-voltage flags: unreadable")
        else:
            lines.append(
                f"- under-voltage now: {'yes' if flags['under_voltage_now'] else 'no'}; "
                f"under-voltage occurred: {'yes' if flags['under_voltage_occurred'] else 'no'}"
            )
        for supply in probe["power_supply"]:
            values = ", ".join(f"{k}={v}" for k, v in supply["values"].items())
            lines.append(f"- power supply {supply['name']} ({supply['type']}): {values}")
        for fact in probe["daemon_facts"]:
            lines.append(f"- daemon {fact['source']}: {fact['path']} = {fact['value']}")
        for path in probe["daemon_paths"]:
            lines.append(f"- daemon route named for power: {path}")
    if runs:
        lines += [
            "",
            "| workload | charging | runtime (h:mm:ss) | good to (s) | heartbeats | gap |",
            "|---|---|---|---|---|---|",
        ]
        for run in runs:
            lines.append(
                f"| {run['workload']} | {run['charging'] or 'not noted'} | "
                f"{_hms(run['runtime_s'])} | {run['uncertainty_s']:g} | {run['heartbeats']} | "
                f"{'GAP' if run['gap_warning'] else 'no'} |"
            )
        for run in runs:
            for key, seen in run["facts_seen"].items():
                lines.append(f"- {run['workload']} run, {key} {seen['first']} to {seen['last']}")
    lines.append("")
    return "\n".join(lines)
