"""Teach a move: gravity compensation on, a person moves the head, we record.

Priority is the player's: a muted body, or something above expression
holding the head, refuses before anything moves. Gravity compensation is
on only for the recording and is always turned off after it, even when
the recording fails; the pose is then held where the hand left it. The
state feed is read at the rate the player streams back at. A stop, or the
duration cap, ends the recording and keeps what was taught so far.
Offline, no model.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol

from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.hal.seam import BodyProfile, HeadActuator, StateFrame, Teachable
from maipai_body.presence.arbitration import ArbitrationState, expression_may_drive

from .player import TICK_S, MoveRefused
from .recorded_move import RecordedMove
from .recorder import MoveRecorder
from .store import MoveStore


class _Body(Teachable, HeadActuator, Protocol):
    """A body that can be taught: the seam's teach calls plus its actuator."""


RATE_HZ = 1.0 / TICK_S
MAX_DURATION_S = 60.0


class TeachSession:
    def __init__(
        self,
        body: _Body,
        store: MoveStore,
        *,
        profile: BodyProfile = REACHY_MINI_PROFILE,
        max_duration_s: float = MAX_DURATION_S,
    ) -> None:
        self._body = body
        self._store = store
        self._profile = profile
        self._max_duration_s = max_duration_s
        self._stopped = threading.Event()

    def stop(self) -> None:
        self._stopped.set()

    def teach(
        self,
        name: str,
        arbitration: ArbitrationState,
        *,
        muted: bool = False,
        replace: bool = False,
        on_frame: Callable[[StateFrame], None] | None = None,
    ) -> RecordedMove:
        if muted:
            raise MoveRefused("the body is muted")
        if not expression_may_drive(arbitration):
            raise MoveRefused("something with higher priority owns the head")
        self._store.check_name(name, replace=replace)  # before the head goes limp

        self._stopped.clear()
        recorder = MoveRecorder(self._profile)
        self._body.enable_gravity_compensation()
        try:
            feed = self._body.state_feed(RATE_HZ)
            try:
                for frame in feed:
                    recorder.add(frame)
                    if on_frame is not None:
                        on_frame(frame)
                    if self._stopped.is_set() or recorder.elapsed_s >= self._max_duration_s:
                        break
            finally:
                feed.close()
        finally:
            try:
                self._body.disable_gravity_compensation()
            finally:
                self._body.hold()
        self._store.save(name, recorder.to_json(f"taught by hand: {name}"), replace=replace)
        return self._store.load(name)
