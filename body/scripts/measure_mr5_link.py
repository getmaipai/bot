"""M-R5: the link. Wi-Fi loss mid-turn, mid-sentence and while listening.

Per design record section 12 and section 7: ``cancel`` raised, the pose
settled, the one line spoken on reconnect if a turn was lost, and the
reconnection time p50 and p95.

The harness runs the real conversation loop against a stand-in hub on
loopback and takes the link down by software: ``reset`` (a polite teardown,
noticed at once) and ``blackhole`` (nothing answers, so the body finds out
only through its own client timeouts, the realistic Wi-Fi case). What it
measures is the body's side: how long to the cancel, how long to a still
head, what the reconnect clock is, and that the line is spoken once.

Simulator (needs ``uv run --extra sim reachy-mini-daemon --sim --headless
--no-media`` answering on port 8000; from ``body/``)::

    uv run python scripts/measure_mr5_link.py --mode sim --trials 8 --record

Blackhole trials wait out the production client timeouts (the turn and tts
streams read for up to 120 s), so each takes minutes; ``--blackhole-trials 0``
skips them.

On the unit, run it on the robot (the daemon is local; the stand-in hub is
on the robot's own loopback, so this gives the real motors' settling and the
real run loop on the Compute Module, not the radio)::

    /venvs/apps_venv/bin/python scripts/measure_mr5_link.py --mode unit \\
        --image-release <release> --trials 10 --record

The radio itself is a separate measurement on the same script. Give it the
real hub's address and the two commands that switch the radio, and run it
detached from your SSH session (the connection will drop; use ``tmux`` or
``systemd-run --scope``)::

    /venvs/apps_venv/bin/python scripts/measure_mr5_link.py --mode unit --trials 0 \\
        --blackhole-trials 0 --hub-url http://<hub address>:<port> \\
        --wifi-off "nmcli radio wifi off" --wifi-on "nmcli radio wifi on" \\
        --wifi-outage-s 20 --wifi-trials 5 --record

Output: ``<out-dir>/M-R5-<mode>-<date>.json`` (default ``measurements/``)
and, with ``--record``, the section ``M-R5: the link (<mode>)`` in
``docs/dev/measurements.md``. No host address is ever written.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import requests

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.measure.link_loss import (
    SCENARIOS,
    LinkLossBench,
    run_trial,
    stratified_outages,
    summarize_trials,
)
from maipai_body.measure.report import daemon_version_from, link_loss_section
from maipai_body.measure.run_header import new_run_header, record_section, write_run
from maipai_body.measure.stand_in_hub import StandInHub
from maipai_body.measure.wifi_cycle import run_wifi_cycle_trial

MEASUREMENTS_MD = Path(__file__).parent.parent.parent / "docs" / "dev" / "measurements.md"
# The turn and tts clients read for up to 120 s (turn_client.py, tts_playback.py).
BLACKHOLE_CANCEL_TIMEOUT_S = 150.0


def _hub_probe(url: str):
    def probe() -> bool:
        return requests.get(url, timeout=1.0).status_code < 500

    return probe


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--mode", choices=("sim", "unit"), required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--trials", type=int, default=8, help="reset trials per scenario")
    parser.add_argument("--blackhole-trials", type=int, default=1)
    parser.add_argument("--report-interval", type=float, default=15.0)
    parser.add_argument("--scenarios", nargs="*", default=list(SCENARIOS), choices=SCENARIOS)
    parser.add_argument("--hub-url", default=None, help="the real hub, for the Wi-Fi cycle only")
    parser.add_argument("--wifi-off", default=None)
    parser.add_argument("--wifi-on", default=None)
    parser.add_argument("--wifi-outage-s", type=float, default=20.0)
    parser.add_argument("--wifi-trials", type=int, default=0)
    parser.add_argument("--image-release", default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("measurements"))
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()

    if args.wifi_trials and not (args.mode == "unit" and args.hub_url):
        parser.error("--wifi-trials needs --mode unit and --hub-url")
    if args.wifi_trials and not (args.wifi_off and args.wifi_on):
        parser.error("--wifi-trials needs both --wifi-off and --wifi-on")

    header = new_run_header(
        row="M-R5",
        mode=args.mode,
        profile_id=REACHY_MINI_PROFILE.id,
        daemon_version=daemon_version_from(args.host, args.port),
        image_release=args.image_release,
    )

    summaries: list[dict] = []
    trials: list[dict] = []
    if args.trials or args.blackhole_trials:
        body = ReachyMiniClient(REACHY_MINI_PROFILE, host=args.host, port=args.port)
        try:
            for fault, count, cancel_timeout_s in (
                ("reset", args.trials, 10.0),
                ("blackhole", args.blackhole_trials, BLACKHOLE_CANCEL_TIMEOUT_S),
            ):
                for scenario in args.scenarios if count else []:
                    with StandInHub(tts_seconds=1.0) as hub:
                        bench = LinkLossBench(
                            body, REACHY_MINI_PROFILE, hub, report_interval_s=args.report_interval
                        )
                        bench.start()
                        try:
                            rows = []
                            # reset trials spread their outages across the report interval so
                            # the reconnect p50 and p95 describe all of it; a blackhole is
                            # already down for the client's whole timeout.
                            outages = (
                                stratified_outages(count, interval_s=args.report_interval)
                                if fault == "reset"
                                else [0.0] * count
                            )
                            for i in range(count):
                                print(f"{scenario} / {fault}: trial {i + 1} of {count}", flush=True)
                                rows.append(
                                    run_trial(
                                        bench,
                                        scenario,
                                        fault,
                                        cancel_timeout_s=cancel_timeout_s,
                                        recover_timeout_s=max(30.0, args.report_interval * 3),
                                        outage_s=outages[i],
                                    )
                                )
                        finally:
                            bench.stop()
                    trials += rows
                    summaries.append(
                        {"scenario": scenario, "mode": fault, **summarize_trials(rows)}
                    )
        finally:
            body.disconnect()

    wifi_rows: list[dict] = []
    for i in range(args.wifi_trials):
        print(f"wifi cycle: trial {i + 1} of {args.wifi_trials}", flush=True)
        wifi_rows.append(
            run_wifi_cycle_trial(
                off_command=args.wifi_off,
                on_command=args.wifi_on,
                outage_s=args.wifi_outage_s,
                probe=_hub_probe(args.hub_url),
            )
        )

    path = write_run(
        args.out_dir, header, [{"summaries": summaries, "trials": trials, "wifi": wifi_rows}]
    )
    print(f"wrote {path}")
    if args.record:
        written = record_section(
            MEASUREMENTS_MD,
            f"## M-R5: the link ({args.mode})",
            link_loss_section(header, summaries, wifi_rows=wifi_rows),
            fallback_dir=args.out_dir,
        )
        print(f"recorded in {written}")


if __name__ == "__main__":
    main()
