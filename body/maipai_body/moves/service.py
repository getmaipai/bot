"""The two ways a move starts: a person's ask, or the plan's ``react`` slot.

Nothing here reads a cue, an emotion or a sentiment, and
``maipai_body.expression`` never imports this module. A move plays only
because someone asked for it by name or the reply plan named it.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from maipai_body.presence.arbitration import ArbitrationState

from .player import MovePlayer, MoveRefused
from .recorded_move import RecordedMove

_ASK = re.compile(r"\b(?:do|play|perform|show(?: me)?)\b")


def _stem(name: str) -> str:
    return re.sub(r"[\d_]+$", "", name).replace("_", " ").strip()


def parse_move_request(text: str, names: list[str]) -> str | None:
    """The move a person asked for, or ``None``. Needs an ask verb: a mood is not an ask."""
    lowered = text.lower()
    verb = _ASK.search(lowered)
    if verb is None:
        return None
    tail = lowered[verb.end() :]
    for name in names:
        stem = _stem(name)
        if stem and re.search(rf"\b{re.escape(stem)}\b", tail):
            return name
    return None


class MovesService:
    def __init__(
        self,
        player: MovePlayer,
        load: Callable[[str], RecordedMove],
        names: list[str],
    ) -> None:
        self._player = player
        self._load = load
        self._names = names

    def ask(self, text: str, arbitration: ArbitrationState, *, muted: bool = False) -> str | None:
        """Play the move a person asked for; return its name, or ``None`` if none matched."""
        name = parse_move_request(text, self._names)
        if name is None:
            return None
        self._player.play(self._load(name), arbitration, muted=muted)
        return name

    def react(
        self,
        name: str,
        arbitration: ArbitrationState,
        *,
        react_allowed: bool,
        muted: bool = False,
    ) -> None:
        """Play the move a reply plan named at its ``react`` slot, only if the plan allows it."""
        if not react_allowed:
            raise MoveRefused("the plan does not allow a react move")
        self._player.play(self._load(name), arbitration, muted=muted)
