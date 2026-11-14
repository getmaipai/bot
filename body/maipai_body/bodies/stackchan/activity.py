"""One place that names what the robot was asked to do that could make it sound or move.

Owner 2026-11-14: the robot beeped and nothing in the log said why. Every host call that can make
the unit play a sound, change its sound policy, change its face, or move on its own writes one
``robot activity:`` line here, so a beep heard at 13:21 can be matched to the line at 13:21 without
a firmware flash. The lines carry words and numbers only, never audio, pictures, titles or names.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("maipai_body.bodies.stackchan.activity")


def log_activity(kind: str, detail: str = "") -> None:
    """``robot activity: <kind> <detail>``; never raises."""
    try:
        logger.info("robot activity: %s%s", kind, f" {detail}" if detail else "")
    except Exception:  # a log line must never break the robot
        pass
