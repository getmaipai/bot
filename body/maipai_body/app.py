"""MaiPai Bot's Reachy Mini app: the daemon's one running app.

Registered under the ``reachy_mini_apps`` entry point (``pyproject.toml``)
as ``MaiPaiBody``. Builds the Reachy Mini client through the HAL seam
from the ``ReachyMini`` handle the daemon hands it, holds neutral, logs
one line per state change, and honors ``stop_event`` and SIGINT within
one second. Expression, speech and the household link are out of scope
(RM-02 onward); this is the app scaffold RM-03 asks for.
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable

from reachy_mini import ReachyMini, ReachyMiniApp

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.hal.errors import BodyLost
from maipai_body.hal.seam import AntennaPositions, HeadActuator, HeadPose

logger = logging.getLogger("maipai_body.app")

_NEUTRAL_POSE = HeadPose()
_NEUTRAL_ANTENNAS = AntennaPositions(left=0.0, right=0.0)
_NEUTRAL_DURATION_S = 1.0
_STOP_POLL_INTERVAL_S = 0.1

_STATE_STARTING = "starting"
_STATE_HOLDING_NEUTRAL = "holding_neutral"
_STATE_BODY_LOST = "body_lost"
_STATE_STOPPED = "stopped"


def _sigint_handler(stop_event: threading.Event) -> Callable[[int, object], None]:
    """Return a handler that turns SIGINT into a normal stop_event.set()."""

    def handler(signum: int, frame: object) -> None:
        logger.info("SIGINT received")
        stop_event.set()

    return handler


def _log_state(state: str) -> None:
    logger.info("state: %s", state)


def run_body(client: HeadActuator, stop_event: threading.Event) -> None:
    """The app's run loop: hold neutral until told to stop.

    A free function, not a method, so the deterministic suite drives it
    directly against ``fake.FakeReachyMiniClient`` with no daemon and no
    ``ReachyMiniApp`` instance (whose ``__init__`` probes for a daemon on
    localhost, which this loop has no need of).
    """
    _log_state(_STATE_STARTING)
    try:
        client.goto(
            pose=_NEUTRAL_POSE,
            antennas=_NEUTRAL_ANTENNAS,
            body_yaw=0.0,
            duration_s=_NEUTRAL_DURATION_S,
        )
        client.hold()
        _log_state(_STATE_HOLDING_NEUTRAL)
        while not stop_event.wait(_STOP_POLL_INTERVAL_S):
            pass
    except BodyLost:
        _log_state(_STATE_BODY_LOST)
    finally:
        _log_state(_STATE_STOPPED)


class MaiPaiBody(ReachyMiniApp):
    """The MaiPai body, run by the daemon as its one app."""

    custom_app_url: str | None = None

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        """Run the body: install the SIGINT handler, then run_body until stopped."""
        previous_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _sigint_handler(stop_event))
        try:
            client = ReachyMiniClient(REACHY_MINI_PROFILE, reachy=reachy_mini)
            run_body(client, stop_event)
        finally:
            signal.signal(signal.SIGINT, previous_handler)


if __name__ == "__main__":
    # The daemon starts an installed app by running its entry point's
    # module as `python -m <module>` in its own subprocess (never by
    # importing the class directly), so this block is the actual thing
    # that runs: found live, RM-03's first daemon-driven start finished
    # in under a second with no error because this block was missing
    # and `python -m maipai_body.app` had nothing to do.
    app = MaiPaiBody()
    try:
        app.wrapped_run()
    except KeyboardInterrupt:
        app.stop()
