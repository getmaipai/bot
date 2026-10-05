"""LINK-STATE-01: the queue rule and the replay rule.

Rungs 0 to 2 queue nothing: the funnel's gate is built with
``accepting=False``, ``offer`` keeps nothing (only a count of refusals, never
the text), and the status line says "Nothing is saved for later." A later
text queue (not built here) would use the same gate with ``accepting=True``
and replays only after the person confirms: ``begin_replay`` runs nothing,
and a write or physical tool, like any queued text, runs only when a
:class:`ConfirmationEvent` names its item (the approval design).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger("maipai_body.link.replay")


@dataclass(frozen=True)
class ToolCall:
    name: str
    kind: Literal["read", "write", "physical"]


@dataclass(frozen=True)
class ReplayItem:
    item_id: str
    text: str
    tool: ToolCall | None = None


@dataclass(frozen=True)
class ConfirmationEvent:
    item_id: str


class ReplayGate:
    def __init__(self, execute: Callable[[ReplayItem], None], *, accepting: bool) -> None:
        self._execute = execute
        self._accepting = accepting
        self._pending: dict[str, ReplayItem] = {}
        self._replaying = False
        self.refused = 0

    @property
    def accepting(self) -> bool:
        return self._accepting

    @property
    def pending(self) -> tuple[ReplayItem, ...]:
        return tuple(self._pending.values())

    def offer(self, item: ReplayItem) -> bool:
        if not self._accepting:
            self.refused += 1
            return False
        self._pending[item.item_id] = item
        return True

    def begin_replay(self) -> tuple[ReplayItem, ...]:
        """Returns what is waiting for a confirmation. Runs nothing."""
        self._replaying = True
        return self.pending

    def handle(self, event: ConfirmationEvent) -> bool:
        """Runs the confirmed item once. True if something ran."""
        if not self._replaying:
            return False
        item = self._pending.pop(event.item_id, None)
        if item is None:
            return False
        self._execute(item)
        return True
