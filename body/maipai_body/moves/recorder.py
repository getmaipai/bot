"""Turns hand-moved state frames into a move in the vendor's JSON shape.

The shape is the one ``recorded_move`` reads (``{description, time,
set_target_data}``), so a taught move and one of Pollen's are the same
kind of file. Times are rebased to the first pose so a move starts at 0,
and the whole recording is checked against the profile's envelope before
it is written: a hand that forced the head past a limit gives a refused
recording, never a clipped one that replays differently from what was
taught. Offline: no connection, no model.
"""

from __future__ import annotations

from typing import Any

from maipai_body.bodies.reachy_mini.envelope import clamp_target
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.hal.seam import BodyProfile, StateFrame

from .recorded_move import InvalidMove, RecordedMove, pose_to_matrix


class TooShort(InvalidMove):
    """Fewer than two poses were recorded; there is no motion to replay."""


class MoveRecorder:
    def __init__(self, profile: BodyProfile = REACHY_MINI_PROFILE) -> None:
        self._profile = profile
        self._frames: list[StateFrame] = []

    def add(self, frame: StateFrame) -> None:
        """Keep a frame that carries a pose and moves the clock forward; drop the rest."""
        if frame.head_pose is None or frame.antennas is None:
            return
        if self._frames and frame.t_received_ns <= self._frames[-1].t_received_ns:
            return
        self._frames.append(frame)

    @property
    def elapsed_s(self) -> float:
        if len(self._frames) < 2:
            return 0.0
        return (self._frames[-1].t_received_ns - self._frames[0].t_received_ns) / 1e9

    def to_json(self, description: str) -> dict[str, Any]:
        if len(self._frames) < 2:
            raise TooShort("a move needs at least two recorded poses")
        start = self._frames[0].t_received_ns
        for frame in self._frames:
            assert frame.head_pose is not None and frame.antennas is not None
            clamp_target(self._profile, frame.head_pose, frame.antennas, frame.body_yaw)
        data = {
            "description": description,
            "time": [(f.t_received_ns - start) / 1e9 for f in self._frames],
            "set_target_data": [
                {
                    "head": pose_to_matrix(f.head_pose).tolist(),  # type: ignore[arg-type]
                    "antennas": [f.antennas.left, f.antennas.right],  # type: ignore[union-attr]
                    "body_yaw": f.body_yaw or 0.0,
                }
                for f in self._frames
            ],
        }
        RecordedMove.from_json("recording", data)  # the file we write must read back
        return data
