"""RM-07: what leaves the robot. Capture or read a pcap, label it, check the page.

Groups every connection the robot opened by destination and port, labels
each against the design's allowed list (``maipai_body/measure/netcapture.py``,
``docs/dev/design-reachy-mini-2026-09-27.md`` section 8), prints the table and
exits 1 if anything is not on the list. The privacy page's generated rows
(``docs/user/reachy-mini-privacy.md``) come from the same list.

Exit status: 0 everything listed and the page agrees, 1 an unlisted endpoint or a page
that differs from the generator, 2 a usage problem.

Rehearsal (loopback, a fake hub and optionally a fake stray endpoint; proves the
pipeline, records nothing; needs Linux and root to sniff ``lo``)::

    uv run python scripts/measure_rm07_egress.py --rehearse --stray

A sample or earlier capture::

    uv run python scripts/measure_rm07_egress.py --pcap before.pcap \\
        --robot-ip <robot address> --hub <hub address>:<port>

Check that the page matches the generator (no capture needed; the gate runs this as a test)::

    uv run python scripts/measure_rm07_egress.py --check-page

On the isolated network, on a machine that sees the robot's traffic (the router, or a
bridge; ``tcpdump`` must be installed), for the 24 hours before and after the install::

    /venvs/apps_venv/bin/python scripts/measure_rm07_egress.py --capture <interface> \\
        --seconds 86400 --robot-ip <robot address> --hub <hub address>:<port> \\
        --phase before-install --mode unit --daemon-version <version> \\
        --image-release <release> --record --write-page

``--write-page`` alone rewrites the block from the allowed list (no capture yet).
``--record`` writes the section ``RM-07: what leaves the robot (unit), <phase>`` in
``docs/dev/measurements.md`` and ``--write-page`` replaces the generated block of the
privacy page; with a capture both need ``--mode unit`` and a pass. No household address is
ever written: addresses on the home network are masked.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.measure import netcapture as nc
from maipai_body.measure.report import section_header_lines
from maipai_body.measure.run_header import (
    new_run_header,
    record_section,
    write_run,
)

ROOT = Path(__file__).parent.parent.parent
MEASUREMENTS_MD = ROOT / "docs" / "dev" / "measurements.md"
PAGE = ROOT / "docs" / "user" / "reachy-mini-privacy.md"
CAPTURE_SOURCE = (
    "These rows come from a capture on the unit, recorded in `docs/dev/measurements.md` "
    "(RM-07), before and after MaiPai was installed."
)
PHASES = ("before-install", "after-install")


def _section(
    header: dict,
    phase: str,
    rows: list[nc.Row],
    seconds: float | None,
    ignored_fragments: int = 0,
) -> str:
    lines = [
        f"## RM-07: what leaves the robot ({header['mode']}), {phase}, {header['date']}",
        "",
        *section_header_lines(header),
        f"- capture: {f'{seconds:.0f} s' if seconds else 'from a pcap file'}, "
        "connections the robot opened",
        "- on the list: the design's allowed list, `maipai_body/measure/netcapture.py`",
        "- addresses on the home network are never written down",
        "",
        nc.render_capture_table(rows).rstrip("\n"),
        "",
        *(
            [f"- ignored IP fragments: {ignored_fragments}; capture is incomplete"]
            if ignored_fragments
            else []
        ),
        "- result: "
        + (
            "pass"
            if nc.passes(rows) and not ignored_fragments
            else "FAIL, unlisted endpoint or ignored fragments"
        ),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--pcap", type=Path, help="a pcap or pcapng file to read")
    source.add_argument("--capture", metavar="INTERFACE", help="run tcpdump on this interface")
    source.add_argument("--rehearse", action="store_true", help="loopback with a fake outbound")
    parser.add_argument("--stray", action="store_true", help="rehearsal: add an unlisted endpoint")
    parser.add_argument("--seconds", type=float, default=86400.0, help="capture length")
    parser.add_argument("--robot-ip", help="the robot's address, to tell its connections apart")
    parser.add_argument("--hub", help="the hub, host[:port]; port defaults to 443")
    parser.add_argument("--phase", choices=PHASES, default=None)
    parser.add_argument("--mode", choices=("sim", "unit"), default=None)
    parser.add_argument("--daemon-version", default=None)
    parser.add_argument("--image-release", default=None)
    parser.add_argument(
        "--check-page", action="store_true", help="diff the page against the generator"
    )
    parser.add_argument(
        "--write-page", action="store_true", help="replace the page's generated block"
    )
    parser.add_argument("--record", action="store_true", help="write the measurements.md section")
    parser.add_argument("--out-dir", type=Path, default=Path("measurements"))
    args = parser.parse_args(argv)

    has_source = bool(args.pcap or args.capture or args.rehearse)
    if args.stray and not args.rehearse:
        parser.error("--stray only applies to --rehearse")
    if args.record and not has_source:
        parser.error("--record needs a capture: --pcap or --capture")
    if args.rehearse and (args.record or args.write_page):
        parser.error("a rehearsal is a stand-in and is never recorded or written to the page")
    if (args.record or (args.write_page and has_source)) and args.mode != "unit":
        parser.error("--record and --write-page with a capture need --mode unit")
    if args.record and not (args.phase and args.daemon_version):
        parser.error("--record needs --phase and --daemon-version")
    if (args.pcap or args.capture) and not (args.robot_ip and args.hub):
        parser.error("--pcap and --capture need --robot-ip and --hub")

    rows: list[nc.Row] | None = None
    seconds = None
    diagnostics = nc.CaptureDiagnostics()
    if has_source:
        if args.rehearse:
            tmp = Path(tempfile.mkdtemp(prefix="rm07-rehearsal-"))
            try:
                result = nc.rehearse(tmp / "rehearsal.pcap", stray=args.stray)
            except nc.CaptureUnavailable as err:
                print(f"not run: {err}", file=sys.stderr)
                return 2
            pcap_path, hub, robot_ip = result.pcap, result.hub, "127.0.0.1"
            print(
                "rehearsal: loopback, a fake hub"
                + (" and a fake stray endpoint" if args.stray else "")
            )
        else:
            hub, robot_ip = nc.HubTarget.parse(args.hub), args.robot_ip
            if args.capture:
                args.out_dir.mkdir(parents=True, exist_ok=True)
                pcap_path = args.out_dir / f"RM-07-{args.phase or 'capture'}.pcap"
                seconds = args.seconds
                try:
                    nc.capture_tcpdump(args.capture, pcap_path, seconds=seconds)
                except RuntimeError as err:
                    print(f"not run: {err}", file=sys.stderr)
                    return 2
            else:
                pcap_path = args.pcap
        try:
            packets = nc.read_pcap(pcap_path, diagnostics=diagnostics)
        except (OSError, ValueError) as err:
            print(f"cannot read {pcap_path}: {err}", file=sys.stderr)
            return 2
        rows = nc.label_groups(nc.group_egress(packets, robot_ip), hub)
        print(nc.render_capture_table(rows))
        if diagnostics.ignored_fragments:
            print(f"ignored IP fragments: {diagnostics.ignored_fragments}; capture is incomplete")
        bad = nc.unlisted(rows)
        for row in bad:
            print(f"NOT ON THE LIST: {row.proto} {row.host}:{row.port} ({row.flows} flows)")
        if diagnostics.ignored_fragments:
            print("result: FAIL, capture contains ignored IP fragments")
        else:
            print(
                "result: "
                + ("pass" if not bad else f"FAIL, {len(bad)} destination(s) not on the list")
            )

    status = 0 if rows is None or (nc.passes(rows) and diagnostics.ignored_fragments == 0) else 1

    if args.record and rows is not None:
        header = new_run_header(
            row="RM-07",
            mode=args.mode,
            profile_id=REACHY_MINI_PROFILE.id,
            daemon_version=args.daemon_version,
            image_release=args.image_release,
        )
        args.out_dir.mkdir(parents=True, exist_ok=True)
        run = [
            {
                "phase": args.phase,
                "rule": r.rule,
                "proto": r.proto,
                "destination": r.host if not nc._is_private(r.host) else "home network",
                "port": r.port,
                "flows": r.flows,
                "packets": r.packets,
                "bytes_out": r.bytes_out,
            }
            for r in rows
        ]
        run.append({"ignored_ip_fragments": diagnostics.ignored_fragments})
        print(f"wrote {write_run(args.out_dir, header, run, tag=args.phase)}")
        written = record_section(
            MEASUREMENTS_MD,
            f"## RM-07: what leaves the robot ({args.mode}), {args.phase}",
            _section(header, args.phase, rows, seconds, diagnostics.ignored_fragments),
            fallback_dir=args.out_dir,
        )
        print(f"recorded in {written}")

    if args.check_page or args.write_page:
        block = nc.render_page_block(
            rows if has_source else None, source=CAPTURE_SOURCE if has_source else None
        )
        if args.write_page:
            if status:
                print(
                    "not writing the page: the capture has unlisted endpoints or ignored fragments",
                    file=sys.stderr,
                )
                return 1
            PAGE.write_text(nc.replace_page_block(PAGE.read_text(), block))
            print(f"wrote the generated block in {PAGE}")
        else:
            try:
                diff = nc.page_diff(PAGE.read_text(), block)
            except ValueError as err:
                print(f"{PAGE}: {err}", file=sys.stderr)
                return 2
            if diff:
                print("\n".join(diff))
                print("the privacy page differs from the generator")
                return 1
            print("the privacy page matches the generator")
    return status


if __name__ == "__main__":
    sys.exit(main())
