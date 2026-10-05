"""LINK-STATE-01: the offline ladder's parts, handed to the funnel as one value.

``ConversationLoop`` takes an optional :class:`OfflineRungs`. Without one the
loop behaves exactly as before (a lost link ends the turn and owes one line).
With one, the funnel tells the machine when the link is lost, answers wakes
during an outage with rung 1 only, reports ``reconnecting`` and ``sleeping``
as its activity, and lets rung 0 decide when tracking may run.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from maipai_body.link.commands import CommandRecognizer, CommandRouter, Reply
from maipai_body.link.replay import ReplayGate
from maipai_body.link.rung0 import Rung0Cues
from maipai_body.link.state_machine import LinkStateMachine
from maipai_body.link.status import OfflineStatus, build_status


class ClipSpeaker(Protocol):
    """``OfflineSpeaker`` (or a recording fake): says clip ids, if it can."""

    def can_say(self, clip_ids) -> bool: ...

    def say(self, clip_ids, *, stop_event=None) -> bool: ...


TIMER_DONE_CLIP = "cmd.timer_done"


def _no_replay(_item) -> None:
    raise AssertionError("rungs 0 to 2 never replay anything")


@dataclass
class OfflineRungs:
    machine: LinkStateMachine
    rung0: Rung0Cues | None = None
    recognizer: CommandRecognizer | None = None
    router: CommandRouter | None = None
    speaker: ClipSpeaker | None = None
    # The queue rule: rungs 0 to 2 queue nothing, so the gate refuses every offer.
    gate: ReplayGate = field(default_factory=lambda: ReplayGate(_no_replay, accepting=False))
    tz: datetime.tzinfo | None = None
    # The last rung 1 reply, for the app page (text stays visible when unspoken).
    last_reply: Reply | None = None
    # One fast address walk, run on a wake during an outage so a hub that
    # already came back is used at once instead of at the supervisor's next
    # walk. True means the hub answered. Unset means the wake only cues.
    retry_link: Callable[[], bool] | None = None

    def status(self) -> OfflineStatus:
        """Rung 2: the status line built from the machine's real values."""
        return build_status(self.machine.snapshot(), tz=self.tz)

    def status_text(self) -> str:
        return self.status().text

    def timer_due(self) -> None:
        """A local timer fired: the body stirs, and the done clip is spoken if
        the bundle can say it. Local only: nothing here reaches the hub."""
        if self.rung0 is not None:
            self.rung0.stir_body()
        if self.speaker is not None and self.speaker.can_say([TIMER_DONE_CLIP]):
            self.speaker.say([TIMER_DONE_CLIP])
