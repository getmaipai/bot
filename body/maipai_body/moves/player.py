"""Plays a recorded move through the HAL seam.

Eases to the move's first sample with one ``goto`` (so a move never
begins with a jump), then streams ``set_target`` at the recording's own
timing. The whole move is checked against the profile's envelope before
anything moves, so an out-of-envelope recording never plays halfway.
Arbitration decides who may drive; a muted body plays nothing; ``stop``
ends playback with a ``hold``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from maipai_body.bodies.reachy_mini.envelope import clamp_target
from maipai_body.hal.seam import BodyProfile, HeadActuator
from maipai_body.presence.arbitration import ArbitrationState, expression_may_drive

from .recorded_move import RecordedMove

LEAD_IN_S = 0.5
TICK_S = 0.02  # 50 Hz, the rate the vendor's own move player streams at


class MoveRefused(RuntimeError):
    """Playback is not allowed right now (muted, or a higher priority owns the head)."""


class MovePlayer:
    def __init__(
        self,
        client: HeadActuator,
        profile: BodyProfile,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._profile = profile
        self._sleep = sleep
        self._monotonic = monotonic
        self._stopped = threading.Event()

    def stop(self) -> None:
        self._stopped.set()

    def play(
        self, move: RecordedMove, arbitration: ArbitrationState, *, muted: bool = False
    ) -> None:
        if muted:
            raise MoveRefused("the body is muted")
        if not expression_may_drive(arbitration):
            raise MoveRefused("something with higher priority owns the head")
        for frame in move.frames:
            clamp_target(self._profile, frame.pose, frame.antennas, frame.body_yaw)

        self._stopped.clear()
        first = move.frames[0]
        self._client.goto(
            pose=first.pose, antennas=first.antennas, body_yaw=first.body_yaw, duration_s=LEAD_IN_S
        )
        start = self._monotonic()
        while True:
            if self._stopped.is_set():
                self._client.hold()
                return
            elapsed = self._monotonic() - start
            frame = move.sample(elapsed)
            self._client.set_target(
                pose=frame.pose, antennas=frame.antennas, body_yaw=frame.body_yaw
            )
            if elapsed >= move.duration_s:
                return
            self._sleep(TICK_S)
