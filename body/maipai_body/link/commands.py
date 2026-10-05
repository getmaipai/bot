"""LINK-STATE-01 rung 1: a closed list of fixed local commands.

While the hub is out of reach the wake word still works, and what follows it
is matched against six fixed commands (stop, quieter, louder, timer, what
time is it, are you connected). Nothing outside the list runs a turn, and
the replies are fixed: each is a clip id plus its text, shown on the app
page and spoken only when the bundle can say every id of it.

The recognizer is an interface. The sherpa-onnx keyword spotter named in
``dev.md``'s wake row is the intended implementation; its CPU and
false-accept cost on the Compute Module beside the wake model is UNVERIFIED
(see ``docs/dev/offline-ladder-unit-checks.md`` for the command that
measures it). Until that row is recorded the app wires no recognizer, and a
wake during an outage is ignored.

Replies that need clips the G4b bundle does not have yet (``cmd.*`` and the
digits 0 and 1) are listed by :func:`missing_clip_ids`: G4b owns the clip
set, this module only names what it needs.
"""

from __future__ import annotations

import datetime
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from maipai_body.link.state_machine import LinkStateMachine
from maipai_body.link.status import build_status
from maipai_body.speech.offline_clips import Manifest, char_clip_id

VOLUME_STEP = 10
DEFAULT_TIMER_S = 300.0  # a fixed five minutes; the list has no way to say another


class LocalCommand(StrEnum):
    STOP = "stop"
    QUIETER = "quieter"
    LOUDER = "louder"
    TIMER = "timer"
    TIME = "time"
    CONNECTED = "connected"


COMMAND_PHRASES: dict[LocalCommand, tuple[str, ...]] = {
    LocalCommand.STOP: ("stop",),
    LocalCommand.QUIETER: ("quieter", "be quieter"),
    LocalCommand.LOUDER: ("louder", "be louder"),
    LocalCommand.TIMER: ("timer", "set a timer"),
    LocalCommand.TIME: ("what time is it",),
    LocalCommand.CONNECTED: ("are you connected",),
}

_PHRASE_TO_COMMAND = {p: c for c, phrases in COMMAND_PHRASES.items() for p in phrases}


def route_phrase(heard: str) -> LocalCommand | None:
    """The command a heard phrase names, or ``None``. Case and punctuation
    are ignored; the phrase must be on the list in full."""
    normalized = " ".join(re.sub(r"[^a-z' ]", " ", heard.lower()).split())
    return _PHRASE_TO_COMMAND.get(normalized)


class CommandRecognizer(Protocol):
    """Listens after a wake and returns what was said, or ``None``. A real
    one is the keyword spotter; tests use a scripted fake."""

    def listen(self, capture, stop_event: threading.Event) -> str | None: ...


class VolumeControl(Protocol):
    """SEAM: the body's output volume (the daemon exposes ``/api/volume``).
    Not wired to a real body yet: it needs the unit to pick audible steps."""

    def get_level(self) -> int: ...

    def set_level(self, level: int) -> None: ...


class LocalTimers:
    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._deadlines: list[float] = []

    def start(self, seconds: float) -> None:
        self._deadlines.append(self._clock() + seconds)

    def pop_due(self) -> bool:
        now = self._clock()
        due = [d for d in self._deadlines if d <= now]
        self._deadlines = [d for d in self._deadlines if d > now]
        return bool(due)


@dataclass(frozen=True)
class Reply:
    text: str
    clip_ids: tuple[str, ...]


# Fixed replies: clip id and the text that clip speaks (what G4b renders).
FIXED_CLIPS: dict[str, str] = {
    "cmd.stopped": "Stopped.",
    "cmd.quieter": "Quieter.",
    "cmd.louder": "Louder.",
    "cmd.timer_set": "Timer set.",
    "cmd.timer_done": "Your timer is done.",
    "cmd.time_prefix": "It is",
}


def missing_clip_ids(manifest: Manifest) -> set[str]:
    """The clip ids rung 1 can ask for that the bundle's manifest lacks."""
    wanted = set(FIXED_CLIPS) | {char_clip_id(str(d)) for d in range(10)}
    have = {c.id for c in manifest.clips}
    return wanted - have


class CommandRouter:
    def __init__(
        self,
        *,
        volume: VolumeControl,
        timers: LocalTimers,
        machine: LinkStateMachine,
        wall_clock: Callable[[], float],
        tz: datetime.tzinfo | None = None,
        timer_s: float = DEFAULT_TIMER_S,
    ) -> None:
        self._volume = volume
        self._timers = timers
        self._machine = machine
        self._wall_clock = wall_clock
        self._tz = tz
        self._timer_s = timer_s

    def handle(self, command: LocalCommand) -> Reply:
        if command is LocalCommand.STOP:
            return self._fixed("cmd.stopped")
        if command is LocalCommand.QUIETER:
            self._volume.set_level(max(0, self._volume.get_level() - VOLUME_STEP))
            return self._fixed("cmd.quieter")
        if command is LocalCommand.LOUDER:
            self._volume.set_level(min(100, self._volume.get_level() + VOLUME_STEP))
            return self._fixed("cmd.louder")
        if command is LocalCommand.TIMER:
            self._timers.start(self._timer_s)
            return self._fixed("cmd.timer_set")
        if command is LocalCommand.TIME:
            now = datetime.datetime.fromtimestamp(self._wall_clock(), self._tz)
            digits = now.strftime("%H%M")
            return Reply(
                f"It is {now:%H:%M}.",
                ("cmd.time_prefix", *(char_clip_id(d) for d in digits)),
            )
        status = build_status(self._machine.snapshot(), tz=self._tz)
        return Reply(status.text, status.clip_ids)

    @staticmethod
    def _fixed(clip_id: str) -> Reply:
        return Reply(FIXED_CLIPS[clip_id], (clip_id,))
