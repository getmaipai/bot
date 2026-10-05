"""``python -m maipai_body.dashboard``: serve a body's dashboard.

``--fake`` replays recorded fixtures with no daemon. Without it, connects
to a Reachy Mini daemon (the simulator, ``reachy-mini-daemon --sim``, or
the unit) at ``--daemon-host:--daemon-port``. This launcher is the one
place the package names a body; the page and server never do.
"""

from __future__ import annotations

import argparse
import signal
import threading

from .server import DashboardServer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maipai_body.dashboard", description=__doc__)
    parser.add_argument("--fake", action="store_true", help="replay recorded fixtures")
    parser.add_argument("--daemon-host", default="localhost")
    parser.add_argument("--daemon-port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1", help="address to serve on")
    parser.add_argument("--port", type=int, default=8050)
    args = parser.parse_args(argv)

    from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE as profile

    if args.fake:
        from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient

        client = FakeReachyMiniClient(profile)
    else:
        from maipai_body.bodies.reachy_mini.client import ReachyMiniClient

        client = ReachyMiniClient(profile, host=args.daemon_host, port=args.daemon_port)

    server = DashboardServer(client, profile, host=args.host, port=args.port)
    server.start()
    print(f"dashboard for {profile.id} on http://{server.host}:{server.port}/", flush=True)
    done = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: done.set())
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    done.wait()
    server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
