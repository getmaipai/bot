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
