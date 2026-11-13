"""Repeat what was said and tell what was missed, answered on the robot without asking the hub.

"Say that again", "what did you say", "repeat that" replay the robot's last spoken reply verbatim:
the same synthesized audio frames that were sent to the unit, so it works with the hub away and
costs no model call. "What did I miss" speaks one short summary of the things the robot could not
tell the person in time (an announcement or timer that came while it was muted, in quiet hours or
full quiet, or that nobody was there to hear), then clears the list.

Memory only, by design: nothing here is written to a file, and the logs never hold words, only
counts. The last ``KEEP_REPLIES`` replies are kept per voice session with a ``MAX_BYTES`` cap over
all sessions (oldest dropped first); the missed list keeps ``MAX_MISSED`` items for ``MAX_AGE_S``.
Both are gone after a restart.

Per session: the robot cannot tell who is speaking with any certainty, so a reply is only replayed
to the session that heard it (one session is one connection from the unit), and a reply that was
said to a known person is not replayed to a different known person.

Hooks other modules use: ``MissedLog.note(kind, text, at)`` (the announcement and timer services
call it where they refuse or skip a line) and the ``muted`` callable given to ``RepeatControl``
(true while a hard mute or full quiet is on; the robot then stays silent and keeps the list).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from maipai_body.bodies.stackchan.stop_phrases import normalize
from maipai_body.settings_keys import REPEAT_ENABLED_KEY

logger = logging.getLogger("maipai_body.bodies.stackchan.repeat")

KEEP_REPLIES = 5
MAX_BYTES = 5 * 1024 * 1024
MAX_MISSED = 20
MAX_AGE_S = 24 * 3600.0
MAX_WORDS = 5
SHOWN_ITEMS = 5

NOTHING_TO_REPEAT = "I haven't said anything yet."
NOTHING_MISSED = "Nothing that I know of."

# A short ask can only be "say that again"; any of these words means it is about something else.
_TOPICAL = frozenset(
    {
        "about", "yesterday", "earlier", "when", "we", "last", "before", "today", "tonight",
        "morning", "night", "week", "ago", "because", "why", "how", "who", "where",
    }
)  # fmt: skip
_MODAL = re.compile(r"^(?:(?:can|could|would|will) you )")
_REPLAY = frozenset(
    {
        "say that again", "say it again", "say again", "say that one more time",
        "say it one more time", "say that once more", "repeat that", "repeat it", "repeat",
        "what did you say", "what did you just say", "what'd you say", "what was that",
        "come again", "pardon", "pardon me", "sorry what", "sorry say that again",
        "i didn't catch that", "i missed that", "again", "one more time",
    }
)  # fmt: skip
_LOUDER = re.compile(r"^(?:say|repeat) (?:that|it)(?: again)? louder$")
_SLOWER = re.compile(r"^(?:say|repeat) (?:that|it)(?: again)? (?:slower|more slowly)$")
_MISSED = frozenset(
    {
        "what did i miss", "what have i missed", "did i miss anything", "have i missed anything",
        "anything happen", "anything happened", "did anything happen", "what did i miss today",
    }
)  # fmt: skip


@dataclass(frozen=True)
class RepeatCommand:
    # "again", "louder" or "slower" (replay the last reply; louder bumps the volume one step for
    # the replay), or "missed" (say what the robot could not tell the person).
    kind: str


def parse_repeat_command(text: str | None) -> RepeatCommand | None:
    """The command for a short utterance that is only a repeat or missed ask, else None.

    At most ``MAX_WORDS`` words after fillers ("please", "StackChan") are dropped, and none of the
    topical words, so "what did you say about dinner yesterday" still goes to the hub."""
    heard = normalize(text)
    words = heard.split()
    if not words or len(words) > MAX_WORDS or _TOPICAL.intersection(words):
        return None
    core = _MODAL.sub("", heard)
    if core in _REPLAY:
        return RepeatCommand("again")
    if _LOUDER.match(core):
        return RepeatCommand("louder")
    if _SLOWER.match(core):
        return RepeatCommand("slower")
    if core in _MISSED:
        return RepeatCommand("missed")
    return None


@dataclass(frozen=True)
class SpokenReply:
    text: str
    frames: tuple[bytes, ...]
    speaker: str | None
    seq: int

    @property
    def size(self) -> int:
        return sum(len(f) for f in self.frames) + len(self.text.encode())


class ReplyStore:
    """The last few spoken replies per session, in memory, with a total byte cap."""

    def __init__(self, *, keep: int = KEEP_REPLIES, max_bytes: int = MAX_BYTES) -> None:
        self._keep = keep
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._by_session: dict[str, deque[SpokenReply]] = {}
        self._seq = 0

    def add(
        self, session_id: str, text: str, frames: list[bytes], speaker: str | None = None
    ) -> bool:
        """Keep one reply. False when it is empty or alone larger than the whole cap."""
        if not text or not frames:
            return False
        with self._lock:
            self._seq += 1
            reply = SpokenReply(text, tuple(frames), speaker, self._seq)
            if reply.size > self._max_bytes:
                return False
            queue = self._by_session.setdefault(session_id, deque())
            queue.append(reply)
            while len(queue) > self._keep:
                queue.popleft()
            while self._total_locked() > self._max_bytes:
                self._drop_oldest_locked()
            return True

    def _total_locked(self) -> int:
        return sum(r.size for q in self._by_session.values() for r in q)

    def _drop_oldest_locked(self) -> None:
        oldest = min(
            (s for s, q in self._by_session.items() if q), key=lambda s: self._by_session[s][0].seq
        )
        self._by_session[oldest].popleft()
        if not self._by_session[oldest]:
            del self._by_session[oldest]

    def last(self, session_id: str) -> SpokenReply | None:
        with self._lock:
            queue = self._by_session.get(session_id)
            return queue[-1] if queue else None

    def count(self, session_id: str | None = None) -> int:
        with self._lock:
            if session_id is not None:
                return len(self._by_session.get(session_id, ()))
            return sum(len(q) for q in self._by_session.values())

    def total_bytes(self) -> int:
        with self._lock:
            return self._total_locked()

    def clear(self) -> None:
        with self._lock:
            self._by_session.clear()


def _clock_time(at: float) -> str:
    return datetime.fromtimestamp(at).strftime("%I:%M").lstrip("0")


def _lower_first(text: str) -> str:
    """ "Dinner is ready" reads as "dinner is ready" mid-sentence; "I" and names stay."""
    if len(text) > 1 and text[0].isupper() and text[1].islower() and not text.startswith("I "):
        return text[0].lower() + text[1:]
    return text


class MissedLog:
    """What the robot could not tell the person in time, newest ``MAX_MISSED``, for 24 hours."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        show_time: Callable[[float], str] = _clock_time,
    ) -> None:
        self._clock = clock
        self._show_time = show_time
        self._lock = threading.Lock()
        self._items: deque[tuple[str, str, float]] = deque(maxlen=MAX_MISSED)

    def note(self, kind: str, text: str, at: float | None = None) -> None:
        """The hook: something was refused or skipped (``kind`` is "announcement", "timer",
        "alarm", "orientation"; ``text`` is a short line in the robot's words; ``at`` is epoch
        seconds, now when None)."""
        line = " ".join(str(text or "").split()).rstrip(" .!")
        if not line:
            return
        when = self._clock() if at is None else float(at)
        with self._lock:
            self._items.append((str(kind), line, when))
            count = len(self._items)
        logger.info("StackChan missed list: %d item%s", count, "" if count == 1 else "s")

    def _fresh_locked(self) -> list[tuple[str, str, float]]:
        cutoff = self._clock() - MAX_AGE_S
        while self._items and self._items[0][2] < cutoff:
            self._items.popleft()
        return list(self._items)

    def count(self) -> int:
        with self._lock:
            return len(self._fresh_locked())

    def summary(self) -> str:
        """One short spoken line for what is on the list (does not clear it)."""
        with self._lock:
            items = self._fresh_locked()
        if not items:
            return NOTHING_MISSED
        parts = [f"{_lower_first(text)} at {self._show_time(at)}" for _k, text, at in items]
        extra = len(parts) - SHOWN_ITEMS
        shown = parts[:SHOWN_ITEMS]
        if extra > 0:
            shown[-1:] = [shown[-1], f"{extra} more"]
        body = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + f" and {shown[-1]}"
        return f"While you were away: {body}."

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


@dataclass(frozen=True)
class RepeatAnswer:
    # "replay" (send ``frames`` again; ``louder`` asks for one volume step up for it), "say" (speak
    # ``line``; ``clear_missed`` after), or "silent" (muted: say nothing, change nothing).
    kind: str
    frames: tuple[bytes, ...] = ()
    line: str = ""
    louder: bool = False
    clear_missed: bool = False


class RepeatControl:
    def __init__(
        self,
        store: ReplyStore | None = None,
        missed: MissedLog | None = None,
        *,
        muted: Callable[[], bool] = lambda: False,
    ) -> None:
        self.store = store or ReplyStore()
        self.missed = missed or MissedLog()
        # The named hook for a hard mute or full quiet: while true the robot says nothing.
        self.muted = muted
        self.enabled = True

    def apply_settings(self, values: Mapping[str, Any]) -> None:
        value = values.get(REPEAT_ENABLED_KEY)
        if isinstance(value, bool):
            self.enabled = value
            if not value:
                self.store.clear()

    def parse(self, text: str | None) -> RepeatCommand | None:
        return parse_repeat_command(text) if self.enabled else None

    def record(
        self, session_id: str, text: str, frames: list[bytes], speaker: str | None = None
    ) -> None:
        if self.enabled and not self.muted():
            self.store.add(session_id, text, frames, speaker)

    def answer(
        self, command: RepeatCommand, session_id: str, speaker: str | None = None
    ) -> RepeatAnswer | None:
        """What to do for the command, or None to let the hub answer it (a "louder" with nothing
        to replay is the volume command it always was)."""
        if self.muted():
            return RepeatAnswer("silent")
        if command.kind == "missed":
            return RepeatAnswer("say", line=self.missed.summary(), clear_missed=True)
        reply = self.store.last(session_id)
        if reply is not None and reply.speaker and speaker and reply.speaker != speaker:
            reply = None  # said to someone else: not replayed to this person
        if reply is None:
            if command.kind == "louder":
                return None
            return RepeatAnswer("say", line=NOTHING_TO_REPEAT)
        return RepeatAnswer("replay", frames=reply.frames, louder=command.kind == "louder")
