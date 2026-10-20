"""Logging for the hosted Bot (MAIPAI_HUB_HOST=1).

Python shows only WARNING and above on stderr when nothing configures logging, so the
StackChan voice-session lines (listen, first audio frame, speech-to-text, chat) at INFO never
reached the hub's log. A hosted Bot logs ``maipai_body`` at INFO with a timestamp.
"""

from __future__ import annotations

import logging
import os

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(hosted: bool | None = None, *, root: logging.Logger | None = None) -> None:
    """Idempotent: add a stderr handler once and raise ``maipai_body`` to INFO when hosted."""
    if hosted is None:
        hosted = os.environ.get("MAIPAI_HUB_HOST") == "1"
    root = root if root is not None else logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
        root.setLevel(logging.WARNING)
    if hosted:
        logging.getLogger("maipai_body").setLevel(logging.INFO)
