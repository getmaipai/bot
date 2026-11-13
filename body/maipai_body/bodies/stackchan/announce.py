"""Hub announcements: Home pushes "say this" and the robot says it ("Dinner is ready").

The hub sends a device command ``announce`` with ``{text, urgent?}``. The robot shows the card and
plays the notification tone through the unit's existing reminder tool (a one second reminder: the
upstream firmware draws the card with the text and plays its notification sound when it fires),
then says the line through the body's own speech path. Nothing here needs new firmware.

Gates, in this order (the reply says which one stopped it, so Home can fall back to its own
notice):

* ``robot.announce.enabled`` off (default on): refused;
* muted (``robot.muted``) or full quiet (``robot.quiet``): refused, urgent or not;
* quiet hours or the sensor's night: refused unless ``urgent`` is true ("day only unless urgent");
* a line longer than 200 characters is cut at a word, an empty one is refused.

The two ``robot.muted`` and ``robot.quiet`` keys are read when they are present in the settings
frame and treated as off when they are not; Home owns whether they exist.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Mapping
from typing import Any

from maipai_body.settings_keys import (
    ANNOUNCE_ENABLED_KEY,
    MUTED_KEY,
    QUIET_KEY,
)

logger = logging.getLogger("maipai_body.bodies.stackchan.announce")

TEXT_MAX = 200
SPEAK_FOR_S = 12.0  # keep trying to say it while a turn is busy, then give up
CARD_SECONDS = 1  # the reminder fires this many seconds after it is created
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean_text(text: object) -> str:
    """One line of plain words: control characters dropped, spaces folded, cut at a word."""
    if not isinstance(text, str):
        return ""
    folded = " ".join(_CONTROL.sub(" ", text).split())
    if len(folded) <= TEXT_MAX:
        return folded
    cut = folded[:TEXT_MAX]
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut).rstrip()


class Announcer:
    """Delivers one announcement at a time. ``show`` creates the card and tone on the unit."""

    def __init__(
        self,
        *,
        show: Callable[[str], object],
        say: Callable[[str], bool],
        night: Callable[[], bool] = lambda: False,
        clock: Callable[[], float],
    ) -> None:
        self._show = show
        self._say = say
        self._night = night
        self._clock = clock
        self._lock = threading.Lock()
        self.enabled = True
        self.muted = False
        self.quiet = False
        self._pending: tuple[str, float] | None = None

    def apply_settings(self, values: Mapping[str, Any]) -> None:
        for key, attr in (
            (ANNOUNCE_ENABLED_KEY, "enabled"),
            (MUTED_KEY, "muted"),
            (QUIET_KEY, "quiet"),
        ):
            value = values.get(key)
            if isinstance(value, bool):
                setattr(self, attr, value)

    def refusal(self, urgent: bool) -> str | None:
        """The word for why it would not be said now, or None."""
        if not self.enabled:
            return "disabled"
        if self.muted:
            return "muted"
        if self.quiet:
            return "quiet"
        if self._night() and not urgent:
            return "night"
        return None

    def handle(self, payload: dict) -> dict:
        """The hub's ``announce`` command. Answers {status: delivered | refused, reason?}."""
        text = clean_text(payload.get("text"))
        if not text:
            return {
                "status": "refused",
                "reason": "empty",
                "error": "The announcement had no words. Send the text to say, then try again.",
            }
        urgent = payload.get("urgent") is True
        why = self.refusal(urgent)
        if why is not None:
            return {"status": "refused", "reason": why}
        try:
            self._show(text)
        except Exception:
            logger.warning("announcement card could not be shown", exc_info=True)
            return {
                "status": "refused",
                "reason": "unreachable",
                "error": "The robot did not answer. Check that it is on and connected, "
                "then send it again.",
            }
        with self._lock:
            self._pending = (text, self._clock() + SPEAK_FOR_S)
        return {"status": "delivered"}

    def tick(self) -> None:
        """Say the line once the robot is free; call about once a second."""
        with self._lock:
            pending = self._pending
        if pending is None:
            return
        text, until = pending
        if self._clock() > until:
            with self._lock:
                self._pending = None
            return
        try:
            said = self._say(text)
        except Exception:
            logger.warning("announcement could not be spoken", exc_info=True)
            said = False
        if said:
            with self._lock:
                if self._pending == pending:
                    self._pending = None
