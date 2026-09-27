"""The one "have we lost the daemon" flag a body's parts all share.

Used by both the live client and the fake, so a connection loss behaves
identically (the same exception, the same message, the same refusal to
do anything else until `clear()`) whichever one is running.
"""

from __future__ import annotations

from maipai_body.hal.errors import BodyLost

_LOST_MESSAGE = "the connection was already lost; reconnect before commanding again"


class ConnectionState:
    def __init__(self) -> None:
        self.lost = False

    def check(self) -> None:
        if self.lost:
            raise BodyLost(_LOST_MESSAGE)

    def mark_lost(self, reason: str) -> BodyLost:
        self.lost = True
        return BodyLost(reason)

    def clear(self) -> None:
        self.lost = False
