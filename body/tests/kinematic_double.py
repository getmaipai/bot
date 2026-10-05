"""A command-driven test double for the state feed.

``FakeReachyMiniClient``'s state feed replays a recorded trace whatever
is commanded, which is right for the seam suite but cannot show a
motion following a command. This subclass moves a first-order lag
toward the last commanded target and stamps frames on receipt, so the
M-R2 harness can be proven end to end without a daemon. ``held=True``
models a head someone is holding still: commands are accepted and
nothing moves. ``goto`` blocks for its duration (scaled by ``time_scale``
to keep tests fast), as the real SDK's ``goto_target`` does, so a
primitive's second step starts after its first.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterator

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.hal.seam import AntennaPositions, HeadPose, StateFrame

_AXES = 5  # pitch, roll, yaw, left, right


class KinematicFakeClient(FakeReachyMiniClient):
    def __init__(
        self,
        *args,
        time_constant_s: float = 0.04,
        time_scale: float = 0.25,
        held: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.time_constant_s = time_constant_s
        self.time_scale = time_scale
        self.held = held
        self._from = [0.0] * _AXES
        self._to = [0.0] * _AXES
        self._t0 = time.monotonic()

    def goto(self, pose=None, antennas=None, body_yaw=None, duration_s=0.5, method="minjerk"):
        super().goto(pose, antennas, body_yaw, duration_s, method)
        time.sleep(duration_s * self.time_scale)

    def _now_vector(self) -> list[float]:
        alpha = 1.0 - math.exp(-(time.monotonic() - self._t0) / self.time_constant_s)
        return [a + (b - a) * alpha for a, b in zip(self._from, self._to, strict=True)]

    def _apply(self, pose, antennas, body_yaw) -> None:
        super()._apply(pose, antennas, body_yaw)
        if self.held:
            return
        target = list(self._to)
        if pose is not None:
            target[0], target[1], target[2] = pose.pitch, pose.roll, pose.yaw
        if antennas is not None:
            target[3], target[4] = antennas.left, antennas.right
        self._from = self._now_vector()
        self._to = target
        self._t0 = time.monotonic()

    def state_feed(self, frequency: float = 10.0) -> _KinematicFeed:
        self._require_connected()
        return _KinematicFeed(self, 1.0 / frequency)


class _KinematicFeed:
    def __init__(self, client: KinematicFakeClient, period_s: float) -> None:
        self._client = client
        self._period_s = period_s
        self._seq = 0

    def __iter__(self) -> Iterator[StateFrame]:
        return self

    def __next__(self) -> StateFrame:
        self._client._require_connected()
        time.sleep(self._period_s)
        pitch, roll, yaw, left, right = self._client._now_vector()
        self._seq += 1
        return StateFrame.stamped(
            self._seq,
            head_pose=HeadPose(pitch=pitch, roll=roll, yaw=yaw),
            antennas=AntennaPositions(left=left, right=right),
        )

    def close(self) -> None:
        pass
