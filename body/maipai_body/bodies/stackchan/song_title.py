"""Keeps the song title on the robot's face while the song plays (host side).

The firmware shows a title for 60 seconds, then hides it (patch 123, ``song_title_deadline_``).
Owner 2026-11-14: "why did you stop showing the song name?" The title is set once, when a song is
named, so it vanished a minute into the song. ``TitleKeeper`` sets it again every
``REFRESH_S`` seconds while the song is still playing, and clears it a short grace after the music
is over (or the person pauses or mutes). A title from Home's player (now playing) is kept the same
way until Home clears it.

No firmware change: it only calls ``self.face.song_title`` again. Each refresh is one INFO log line
without the title text.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger("maipai_body.bodies.stackchan.song_title")

TITLE_TOOL = "self.face.song_title"
REFRESH_S = 40.0  # inside the firmware's 60 s
GRACE_S = 15.0  # after the music is over
MIN_SHOW_S = 45.0  # a title is never taken down sooner than this after it was set
HOME_MAX_S = 30 * 60.0  # a Home title with no word from Home for this long is dropped


@dataclass
class TitleSituation:
    muted: bool = False
    full_quiet: bool = False


class TitleKeeper:
    def __init__(
        self,
        send: Callable[[str, dict], object],
        *,
        situation: Callable[[], TitleSituation],
        music_active: Callable[[], bool],
    ) -> None:
        self._send = send
        self._situation = situation
        self._music_active = music_active
        self._lock = threading.Lock()
        self._text = ""
        self._source = ""  # "heard" (named by listening) or "home" (Home's player)
        self._sent_at = 0.0
        self._set_at = 0.0
        self._inactive_since: float | None = None

    @property
    def text(self) -> str:
        return self._text

    def show(self, text: str, now: float, *, source: str = "heard") -> bool:
        """Show a title now and keep it. An empty text clears it. Returns whether the unit
        accepted the call."""
        text = text.strip()
        with self._lock:
            if not text:
                return self._clear_locked("cleared")
            self._text = text
            self._source = source
            self._set_at = now
            self._inactive_since = None
            return self._push_locked(text, now, refresh=False)

    def clear(self, now: float) -> None:
        with self._lock:
            self._clear_locked("cleared")

    def tick(self, now: float) -> None:
        with self._lock:
            if not self._text:
                return
            sit = self._situation()
            if sit.muted or sit.full_quiet:
                self._clear_locked("muted or quiet")
                return
            if self._source == "home":
                if now - self._set_at >= HOME_MAX_S:
                    self._clear_locked("no word from Home")
                    return
            else:
                if self._music_active():
                    self._inactive_since = None
                else:
                    if self._inactive_since is None:
                        self._inactive_since = now
                    if now - self._inactive_since >= GRACE_S and now - self._set_at >= MIN_SHOW_S:
                        self._clear_locked("the music is over")
                        return
            if now - self._sent_at >= REFRESH_S:
                self._push_locked(self._text, now, refresh=True)

    def _push_locked(self, text: str, now: float, *, refresh: bool) -> bool:
        try:
            result = self._send(TITLE_TOOL, {"text": text})
        except Exception as exc:
            logger.warning("StackChan song title: send failed: %s", type(exc).__name__)
            return False
        if result is False:
            logger.info("StackChan song title: the unit refused it")
            return False
        self._sent_at = now
        if refresh:
            logger.info("StackChan song title: refreshed (still playing)")
        return True

    def _clear_locked(self, why: str) -> bool:
        had = bool(self._text)
        self._text = ""
        self._source = ""
        self._inactive_since = None
        if not had:
            return True
        try:
            self._send(TITLE_TOOL, {"text": ""})
        except Exception as exc:
            logger.warning("StackChan song title: clear failed: %s", type(exc).__name__)
            return False
        if why != "cleared":  # a clear someone asked for is logged by the asker
            logger.info("StackChan song title: cleared (%s)", why)
        return True
