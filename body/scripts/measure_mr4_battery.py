"""M-R4: battery. Hardware-only: run it on the unit.

Design record section 12: runtime idle, in conversation every two minutes,
and with tracking on, by the clock from full to the LED's red; whether any
readable fact (a voltage, a charger-present flag) exists; whether it runs
while charging. Until this row exists the card says "battery level unknown".

The script owns the hardware for the run (stop the body app first): it
holds the microphone capture open like the body does, holds the head at
neutral, and does the workload. The wake model's own compute is not part of
it. Each heartbeat is on disk before the next is written, so when the power
dies the last line is the runtime. From ``body/``, on the unit, over the
daemon on localhost; start every run from a full charge::

    # 1. What can the unit say about its charge? (run once, charger in and out)
    uv run python scripts/measure_mr4_battery.py probe --image-release <release>

    # 2. Runtime. Unplug the charger, then start; leave it until the LED is red
    #    and the unit goes quiet. Note the time you saw the red LED against a
    #    stopwatch started with the script. One run per workload, full to red.
    uv run python scripts/measure_mr4_battery.py run --workload idle --charging no
    uv run python scripts/measure_mr4_battery.py run --workload conversation \\
        --utterance-wav <file.wav> --charging no
    uv run python scripts/measure_mr4_battery.py run --workload tracking --charging no
    #    (tracking: keep a face, or a photograph of one, in the camera's view)

    # 3. Does it run while charging? Same command with the charger in, for as
    #    long as you like; the run's own clock shows it kept going.
    uv run python scripts/measure_mr4_battery.py run --workload idle --charging yes \\
        --duration-s 1800

    # 4. After the unit is charged and booted again: the report. --record adds
    #    the section to docs/dev/measurements.md.
    uv run python scripts/measure_mr4_battery.py report --record

``run --rehearse`` exercises the whole run against the simulator's daemon with a null
audio sink and a separate log (``M-R4-rehearsal-heartbeat.jsonl``), which
``report`` never reads.

Output: the heartbeat log ``<out-dir>/M-R4-heartbeat.jsonl`` (appended across
boots; one run per boot), ``<out-dir>/M-R4-unit-probe-<date>.json`` from
``probe``, and the section ``M-R4: battery (unit)`` from ``report``. No
transcript, hostname or recording is ever written.
"""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.hal.seam import AntennaPositions, HeadPose
from maipai_body.measure.battery import (
    HeartbeatLog,
    analyze_runs,
    current_facts,
    daemon_getter,
    probe_battery_facts,
    read_heartbeats,
    run_battery,
)
from maipai_body.measure.budget import BudgetSampler, psutil_lister
from maipai_body.measure.loop_bench import NullAudioIO
from maipai_body.measure.report import battery_section, daemon_version_from
from maipai_body.measure.run_header import new_run_header, upsert_markdown_section, write_run
from maipai_body.measure.turn_driver import (
    NoUsablePairing,
    WavCapture,
    load_utterance,
    open_hub_session,
    run_scripted_turn,
)
from maipai_body.speech.capture import AudioCapture
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.stt_stream import SttStreamClient
from maipai_body.speech.tts_playback import TtsPlaybackClient
from maipai_body.speech.turn_client import TurnClient

MEASUREMENTS_MD = Path(__file__).parent.parent.parent / "docs" / "dev" / "measurements.md"
DEFAULT_PAIRING = Path.home() / ".local/share/maipai-bot/hub-pairing.json"


def _header(args) -> dict:
    return new_run_header(
        row="M-R4",
        mode="unit",
        profile_id=REACHY_MINI_PROFILE.id,
        daemon_version=daemon_version_from(args.host, args.port),
        image_release=args.image_release,
    )


def _probe(args) -> None:
    probe = probe_battery_facts(daemon_get=daemon_getter(f"http://{args.host}:{args.port}"))
    path = write_run(args.out_dir, _header(args), [probe], tag="probe")
    print(json.dumps({k: probe[k] for k in ("readable", "level_readable", "charger_readable")}))
    print(f"wrote {path}")


def _run(args) -> None:
    if args.workload == "conversation" and not args.utterance_wav:
        raise SystemExit("--workload conversation needs --utterance-wav")
    client = ReachyMiniClient(REACHY_MINI_PROFILE, host=args.host, port=args.port)
    audio = NullAudioIO(client) if args.rehearse else client
    capture = AudioCapture(audio)
    stop = threading.Event()
    work = None
    if args.workload == "conversation":
        try:
            cookie, hub_url = open_hub_session(args.pairing)
        except NoUsablePairing as exc:
            raise SystemExit(str(exc)) from exc
        playback = AudioPlayback(audio)
        stt = SttStreamClient(hub_url, cookie)
        turn = TurnClient(hub_url, cookie)
        tts = TtsPlaybackClient(hub_url, cookie, playback)
        utterance = load_utterance(args.utterance_wav)

        def work() -> dict:
            return run_scripted_turn(stt, turn, tts, capture_factory=lambda: WavCapture(utterance))

    sampler = BudgetSampler(processes={}, list_processes=psutil_lister())
    log = HeartbeatLog(
        args.out_dir
        / ("M-R4-rehearsal-heartbeat.jsonl" if args.rehearse else "M-R4-heartbeat.jsonl")
    )

    def drain() -> None:
        # The body keeps the microphone open while idle; so does the run.
        while not stop.is_set():
            capture.poll_blocks()
            stop.wait(0.02)

    try:
        client.goto(
            pose=HeadPose(),
            antennas=AntennaPositions(left=0.0, right=0.0),
            body_yaw=0.0,
            duration_s=1.0,
        )
        capture.start()
        threading.Thread(target=drain, daemon=True).start()
        if args.workload == "tracking":
            client.enable_tracking()
        print(
            f"heartbeat every {args.interval_s:g} s to {log._path}; "
            "Ctrl+C stops it, power loss ends it.",
            flush=True,
        )
        run_battery(
            log,
            workload=args.workload,
            duration_s=args.duration_s,
            interval_s=args.interval_s,
            work_interval_s=args.turn_interval_s,
            work=work,
            read_facts=current_facts,
            read_system=lambda: {
                k: v for k, v in sampler.sample(t_s=0.0).items() if k in ("temp_c", "throttled_raw")
            },
            static_extra={"charging": args.charging, "note": args.note},
            background_work=True,
        )
    except KeyboardInterrupt:
        print("stopped")
    finally:
        stop.set()
        log.append(workload=args.workload, extra={"event": "stopped"})
        log.close()
        if args.workload == "tracking":
            try:
                client.disable_tracking()
            except Exception:
                pass
        capture.stop()
        client.disconnect()


def _report(args) -> None:
    log_path = args.out_dir / "M-R4-heartbeat.jsonl"
    runs = (
        analyze_runs(
            [r for r in read_heartbeats(log_path) if "event" not in r], interval_s=args.interval_s
        )
        if log_path.exists()
        else []
    )
    probe_files = sorted(args.out_dir.glob("M-R4-unit-probe-*.json"))
    probe = json.loads(probe_files[-1].read_text())["rows"][0] if probe_files else None
    if probe is None and not runs:
        raise SystemExit(f"nothing to report under {args.out_dir}")
    for run in runs:
        print(
            f"{run['workload']} (charging {run['charging']}): {run['runtime_s']:.0f} s "
            f"+/- {run['uncertainty_s']:g}, {run['heartbeats']} heartbeats"
        )
    if args.record:
        upsert_markdown_section(
            MEASUREMENTS_MD, "## M-R4: battery (unit)", battery_section(_header(args), probe, runs)
        )
        print(f"updated {MEASUREMENTS_MD}")


def main() -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", default="localhost")
    common.add_argument("--port", type=int, default=8000)
    common.add_argument("--image-release", default=None)
    common.add_argument("--out-dir", type=Path, default=Path("measurements"))
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", parents=[common])

    run = sub.add_parser("run", parents=[common])
    run.add_argument("--workload", choices=("idle", "conversation", "tracking"), required=True)
    run.add_argument("--charging", choices=("yes", "no"), required=True)
    run.add_argument("--utterance-wav", type=Path)
    run.add_argument("--pairing", type=Path, default=DEFAULT_PAIRING)
    run.add_argument("--interval-s", type=float, default=30.0)
    run.add_argument("--turn-interval-s", type=float, default=120.0)
    run.add_argument("--duration-s", type=float, default=24 * 3600.0)
    run.add_argument("--note", default="")
    run.add_argument("--rehearse", action="store_true", help="simulator rehearsal; see above")

    report = sub.add_parser("report", parents=[common])
    report.add_argument("--interval-s", type=float, default=30.0)
    report.add_argument("--record", action="store_true")

    args = parser.parse_args()
    {"probe": _probe, "run": _run, "report": _report}[args.command](args)


if __name__ == "__main__":
    main()
