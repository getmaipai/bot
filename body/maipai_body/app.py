"""MaiPaiBody: the Reachy Mini daemon's own app.

Registered under the `reachy_mini_apps` entry-point group
(`body/pyproject.toml`). The daemon constructs one `MaiPaiBody`, connects
a `ReachyMini` handle to it, and calls `run(reachy_mini, stop_event)` in a
subprocess; it stops the app with SIGINT, which the `if __name__ ==
"__main__"` block below turns into `stop()`.

Expression, speech and the hub link are out of scope here (RM-02, RM-04,
RM-05): this app holds neutral, logs one line per lifecycle state change,
and releases the body cleanly on `stop_event` or SIGINT.
"""

from __future__ import annotations

import logging
import threading
import time

from reachy_mini import ReachyMini, ReachyMiniApp

from maipai_body.bodies.reachy_mini.client import wrap_connected_sdk
from maipai_body.hal.errors import BodyLost
from maipai_body.hal.seam import HeadActuator, HeadPose

logger = logging.getLogger("maipai_body.app")

_STOP_POLL_S = 0.1
_HOLD_REFRESH_S = 2.0
_NEUTRAL_GOTO_S = 1.0


class MaiPaiBody(ReachyMiniApp):
    """The MaiPai body's app: hold neutral, log state, exit clean."""

    custom_app_url: str | None = None

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        body = wrap_connected_sdk(reachy_mini)
        self._run_with_head(body.head, stop_event)

    @staticmethod
    def _run_with_head(head: HeadActuator, stop_event: threading.Event) -> None:
        """The actual run loop, against the seam's `HeadActuator` directly.

        Split out from `run()` so a unit test can drive it with the fake's
        `HeadActuator` (`build_fake_body().head`) and a plain
        `threading.Event`, with no daemon and no `ReachyMini` handle
        needed.
        """
        last_state: str | None = None

        def log_state(state: str) -> None:
            nonlocal last_state
            if state != last_state:
                logger.info("state: %s", state)
                last_state = state

        log_state("starting")
        try:
            head.enable()
            head.goto(HeadPose(), (0.0, 0.0), 0.0, duration_s=_NEUTRAL_GOTO_S)
            head.hold()
            log_state("holding_neutral")

            # A tight wait keeps stop_event/SIGINT responsive; re-affirming
            # the hold happens on its own, slower cadence rather than
            # every tick, so a BodyLost while idle is still caught without
            # `hold()`'s two REST round trips hammering the daemon every
            # `_STOP_POLL_S` and turning an ordinary slow response into a
            # false positive.
            next_hold_at = time.monotonic() + _HOLD_REFRESH_S
            while not stop_event.is_set():
                stop_event.wait(_STOP_POLL_S)
                if stop_event.is_set():
                    break
                now = time.monotonic()
                if now >= next_hold_at:
                    head.hold()
                    next_hold_at = now + _HOLD_REFRESH_S

            log_state("stopping")
        except BodyLost as exc:
            logger.warning("body lost: %s", exc)
            log_state("body_lost")
        finally:
            try:
                head.disable()
            except BodyLost:
                pass
            log_state("stopped")


if __name__ == "__main__":
    # The daemon runs this file as a subprocess and relays its stderr into
    # its own log (reachy_mini.apps.manager: `log_stderr`); without a
    # handler here, `logger.info(...)` below is a silent no-op.
    logging.basicConfig(level=logging.INFO, format="%(name)s - %(message)s")
    app = MaiPaiBody()
    try:
        app.wrapped_run()
    except KeyboardInterrupt:
        app.stop()
