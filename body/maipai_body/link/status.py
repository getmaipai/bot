"""LINK-STATE-01 rung 2: the offline status, a template over real values.

No model and no network. Every value in the text comes from the
:class:`LadderSnapshot` the state machine holds (which the lifecycle and the
address walk filled in): the phase, the address being tried, the attempt
count, the last contact, the path that last answered and the last error. A
value that is absent is left out, never filled in.

The text is always visible (the app page's state frame carries it). It is
spoken only through clip ids: the one existing ``line.unreachable`` clip.
Numbers, addresses and errors are not spoken; the digit clips cover 2 to 9
only (the pairing alphabet), so there is no honest way to say them yet.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from maipai_body.link.state_machine import LadderSnapshot, LinkPhase

NOTHING_SAVED = "Nothing is saved for later."
UNREACHABLE_CLIP = "line.unreachable"


@dataclass(frozen=True)
class OfflineStatus:
    text: str
    clip_ids: tuple[str, ...]


def _clock_time(wall: float, tz: datetime.tzinfo | None) -> str:
    return datetime.datetime.fromtimestamp(wall, tz).strftime("%H:%M")


def _contact(snapshot: LadderSnapshot, tz: datetime.tzinfo | None) -> str:
    if snapshot.last_connected_wall is None:
        return "No contact since starting."
    text = f"Last contact {_clock_time(snapshot.last_connected_wall, tz)}"
    if snapshot.answered_path:
        text += f", over {snapshot.answered_path}"
    return text + "."


def build_status(snapshot: LadderSnapshot, *, tz: datetime.tzinfo | None = None) -> OfflineStatus:
    if snapshot.phase is LinkPhase.CONNECTED:
        return OfflineStatus("Connected to home.", ())

    parts: list[str] = []
    if snapshot.phase is LinkPhase.RECONNECTING:
        parts.append("Can't reach home.")
        if snapshot.current_address:
            trying = f"Trying {snapshot.current_address}"
            if snapshot.attempts:
                trying += f" (attempt {snapshot.attempts})"
            parts.append(trying + ".")
    else:
        parts.append("Asleep, can't reach home.")
        checking = "Still checking"
        if snapshot.attempts:
            noun = "attempt" if snapshot.attempts == 1 else "attempts"
            checking += f", {snapshot.attempts} {noun}"
        if snapshot.current_address:
            checking += f", last tried {snapshot.current_address}"
        parts.append(checking + ".")
    parts.append(_contact(snapshot, tz))
    if snapshot.last_error:
        parts.append(f"Last error: {snapshot.last_error}.")
    parts.append(NOTHING_SAVED)
    return OfflineStatus(" ".join(parts), (UNREACHABLE_CLIP,))
