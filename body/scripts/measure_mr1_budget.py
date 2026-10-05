"""M-R1: the Compute Module budget. Hardware-only: run it on the unit.

Design record section 12: RSS and headroom, CPU per process, temperature
and throttle flags over an hour, a turn every two minutes, for three
configurations. Run each on a fresh boot with nothing else going on, one
after the other, and record all three before reading the decision.

1. The daemon alone (the body app stopped, no turns)::

    uv run python scripts/measure_mr1_budget.py --config daemon --turn-interval-s 0 \\
        --image-release <release> --record

2. The ``pod``-tier body (the app running and paired; the hub does stt and
   tts). The utterance is a 16 kHz 16-bit mono WAV of someone saying
   something a household would say, ending where the speech ends::

    uv run python scripts/measure_mr1_budget.py --config pod \\
        --utterance-wav <file.wav> --image-release <release> --record

3. ``stt`` and ``tts`` on the robot (the ``robot`` tier): the same app, with
   the speech services running on the unit and answering the hub's own stt
   and tts routes at local addresses. ``--process name=pattern`` adds each
   service to the per-process figures; ``--m06-p95-ms`` is the MaiPai
   build's recorded M-06 endpoint-to-transcript p95 (not in this repo yet;
   M-06 is open in the backlog)::

    uv run python scripts/measure_mr1_budget.py --config robot \\
        --utterance-wav <file.wav> --stt-base-url http://127.0.0.1:<port> \\
        --tts-base-url http://127.0.0.1:<port> --process stt=<pattern> \\
        --process tts=<pattern> --m06-p95-ms <figure> --image-release <release> --record

``--stand-in-hub`` rehearses the whole script against a local stand-in hub with
no pairing and no speaker (audio goes to a null sink); it cannot be recorded,
because a stand-in's latencies are not the hub's.

Output: ``<out-dir>/M-R1-unit-<config>-<date>.json`` (default ``measurements/``)
and, with ``--record``, the section ``M-R1: the Compute Module budget, <config>``
in ``docs/dev/measurements.md``. ``--duration-s 60 --turn-interval-s 20`` is a
quick rehearsal; the recorded run is the default hour. Audio plays through
the speaker (it is part of the load); turn off ``--speak`` only to rehearse
quietly. Never a hostname or a transcript is written.

Endpoint to transcript runs from the last sample of the utterance to the
final transcript and so includes the hub's own endpointing silence; M-06's
figure on the MaiPai build is measured around Silero's endpoint decision
instead. The two are comparable as the design's rule uses them (the rule
adds 500 ms), but read them together, not as one definition.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.measure.budget import (
    BudgetSampler,
    psutil_lister,
    robot_tier_decision,
    run_budget,
    summarize_budget,
)
from maipai_body.measure.loop_bench import NullAudioIO
from maipai_body.measure.report import budget_section, daemon_version_from
from maipai_body.measure.run_header import new_run_header, upsert_markdown_section, write_run
from maipai_body.measure.stand_in_hub import StandInHub
from maipai_body.measure.turn_driver import (
    NoUsablePairing,
    WavCapture,
    load_utterance,
    open_hub_session,
    run_scripted_turn,
)
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.stt_stream import SttStreamClient
from maipai_body.speech.tts_playback import TtsPlaybackClient
from maipai_body.speech.turn_client import TurnClient

MEASUREMENTS_MD = Path(__file__).parent.parent.parent / "docs" / "dev" / "measurements.md"
DEFAULT_PAIRING = Path.home() / ".local/share/maipai-bot/hub-pairing.json"


def _session(pairing_path: Path) -> tuple[str, str]:
    try:
        return open_hub_session(pairing_path)
    except NoUsablePairing as exc:
        raise SystemExit(str(exc)) from exc


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--config", choices=("daemon", "pod", "robot"), required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--duration-s", type=float, default=3600.0)
    parser.add_argument("--interval-s", type=float, default=5.0)
    parser.add_argument("--turn-interval-s", type=float, default=120.0, help="0 runs no turns")
    parser.add_argument("--utterance-wav", type=Path)
    parser.add_argument("--pairing", type=Path, default=DEFAULT_PAIRING)
    parser.add_argument("--stt-base-url")
    parser.add_argument("--tts-base-url")
    parser.add_argument("--m06-p95-ms", type=float)
    parser.add_argument(
        "--process",
        action="append",
        default=[],
        metavar="NAME=PATTERN",
        help="a process to track, matched as a substring of its command line ('a|b' for either)",
    )
    parser.add_argument("--speak", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--stand-in-hub", action="store_true", help="rehearsal only; see above")
    parser.add_argument("--image-release", default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("measurements"))
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()

    if args.stand_in_hub and args.record:
        parser.error("--stand-in-hub is a rehearsal: its latencies are not the hub's, never record")
    running_turns = args.turn_interval_s > 0
    if running_turns and not args.utterance_wav:
        parser.error("--utterance-wav is required unless --turn-interval-s is 0")
    if args.config == "robot" and not (args.stt_base_url and args.tts_base_url):
        parser.error("--config robot needs --stt-base-url and --tts-base-url")
    if args.config == "daemon" and running_turns:
        parser.error("--config daemon measures the daemon alone: pass --turn-interval-s 0")

    processes = {
        "daemon": "reachy_mini.daemon|reachy-mini-daemon",
        "body": "maipai_body|maipai_bot|maipai-bot",
    }
    for item in args.process:
        name, _, pattern = item.partition("=")
        if not name or not pattern:
            parser.error(f"--process wants NAME=PATTERN, got {item!r}")
        processes[name] = pattern

    header = new_run_header(
        row="M-R1",
        mode="unit",
        profile_id=REACHY_MINI_PROFILE.id,
        daemon_version=daemon_version_from(args.host, args.port),
        image_release=args.image_release,
    )

    run_turn = lambda: {}  # noqa: E731 - replaced below when turns run
    client = None
    stand_in = None
    if running_turns:
        client = ReachyMiniClient(REACHY_MINI_PROFILE, host=args.host, port=args.port)
        if args.stand_in_hub:
            stand_in = StandInHub(tts_seconds=1.0)
            stand_in.start()
            cookie, hub_url = "rehearsal", stand_in.http_url
            args.stt_base_url = args.stt_base_url or stand_in.stt_url
            playback = AudioPlayback(NullAudioIO(client))
        else:
            cookie, hub_url = _session(args.pairing)
            playback = AudioPlayback(client)
        stt = SttStreamClient(args.stt_base_url or hub_url, cookie)
        turn = TurnClient(hub_url, cookie)
        tts = TtsPlaybackClient(args.tts_base_url or hub_url, cookie, playback)
        utterance = load_utterance(args.utterance_wav)
        run_turn = lambda: run_scripted_turn(  # noqa: E731
            stt, turn, tts, capture_factory=lambda: WavCapture(utterance), speak=args.speak
        )

    sampler = BudgetSampler(processes=processes, list_processes=psutil_lister())
    try:
        samples, turns = run_budget(
            sampler,
            duration_s=args.duration_s,
            interval_s=args.interval_s,
            turn_interval_s=args.turn_interval_s if running_turns else args.duration_s * 2,
            run_turn=run_turn,
            background_turns=True,
        )
    finally:
        if client is not None:
            client.disconnect()
        if stand_in is not None:
            stand_in.stop()
    if not running_turns:
        turns = []

    summary = summarize_budget(samples, turns)
    decision = None
    if args.config == "robot" and args.m06_p95_ms is not None:
        p95 = summary["turns"].get("endpoint_to_transcript_ms", {}).get("p95")
        if p95 is not None:
            decision = robot_tier_decision(
                endpoint_to_transcript_p95_ms=p95,
                m06_p95_ms=args.m06_p95_ms,
                any_throttle=summary["throttled"]["ever_flagged_bits"] != 0,
                turns=summary["turns"]["n"] - summary["turns"]["failed"],
            )
    path = write_run(
        args.out_dir,
        header,
        [
            {
                "config": args.config,
                "summary": summary,
                "decision": decision,
                "samples": samples,
                "turns": turns,
            }
        ],
        tag=f"{args.config}-rehearsal" if args.stand_in_hub else args.config,
    )
    print(f"wrote {path}")
    if decision is not None:
        print(f"decision: {decision}")
    if args.record:
        upsert_markdown_section(
            MEASUREMENTS_MD,
            f"## M-R1: the Compute Module budget, {args.config} (unit)",
            budget_section(header, args.config, summary, decision, duration_s=args.duration_s),
        )
        print(f"updated {MEASUREMENTS_MD}")


if __name__ == "__main__":
    main()
