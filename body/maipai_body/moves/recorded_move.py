"""Pollen's recorded move shape, read against the seam's own types.

A move is one JSON object, ``{"description": str, "time": [float, ...],
"set_target_data": [{"head": 4x4, "antennas": [left, right], "body_yaw":
float}, ...]}``, byte-compatible with the vendor's ``RecordedMove`` so
their library and MOVES-02's recordings are the same files
(``docs/dev/what-we-take-from-pollen-2026-09-28.md``). This is a small
reimplementation of the format's reading and sampling, not a copy of the
vendor file. Between two bracketing samples every field is interpolated
linearly; for the small angles a head move spans that matches the
vendor's pose interpolation to well inside the envelope.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from maipai_body.hal.seam import AntennaPositions, HeadPose


class InvalidMove(ValueError):
    """The JSON is not a well-formed move."""


@dataclass(frozen=True)
class MoveFrame:
    """One sampled instant of a move, in the seam's own types."""

    pose: HeadPose
    antennas: AntennaPositions
    body_yaw: float


def matrix_to_pose(matrix: npt.NDArray[np.float64]) -> HeadPose:
    """A 4x4 head transform to a seam pose (extrinsic xyz: R = Rz(yaw) Ry(pitch) Rx(roll))."""
    rotation = matrix[:3, :3]
    pitch = -math.asin(max(-1.0, min(1.0, float(rotation[2, 0]))))
    roll = math.atan2(rotation[2, 1], rotation[2, 2])
    yaw = math.atan2(rotation[1, 0], rotation[0, 0])
    x, y, z = (float(v) for v in matrix[:3, 3])
    return HeadPose(x=x, y=y, z=z, roll=roll, pitch=pitch, yaw=yaw)


def pose_to_matrix(pose: HeadPose) -> npt.NDArray[np.float64]:
    """A seam pose to a 4x4 head transform, the inverse of ``matrix_to_pose``."""
    cr, sr = math.cos(pose.roll), math.sin(pose.roll)
    cp, sp = math.cos(pose.pitch), math.sin(pose.pitch)
    cy, sy = math.cos(pose.yaw), math.sin(pose.yaw)
    matrix = np.eye(4)
    matrix[:3, :3] = [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]
    matrix[:3, 3] = [pose.x, pose.y, pose.z]
    return matrix


def _lerp(a: float, b: float, frac: float) -> float:
    return a + (b - a) * frac


class RecordedMove:
    def __init__(
        self,
        name: str,
        description: str,
        times: list[float],
        frames: list[MoveFrame],
    ) -> None:
        self.name = name
        self.description = description
        self.times = times
        self.frames = frames

    @property
    def duration_s(self) -> float:
        return self.times[-1]

    @classmethod
    def from_json(cls, name: str, data: dict[str, Any]) -> RecordedMove:
        try:
            times = [float(t) for t in data["time"]]
            samples = data["set_target_data"]
            description = str(data.get("description", ""))
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidMove(f"{name}: not a move ({exc!r})") from exc
        if len(times) < 2:
            raise InvalidMove(f"{name}: a move needs at least two samples")
        if len(times) != len(samples):
            raise InvalidMove(f"{name}: {len(times)} times but {len(samples)} samples")
        if any(b <= a for a, b in zip(times, times[1:], strict=False)):
            raise InvalidMove(f"{name}: times must strictly increase")
        frames: list[MoveFrame] = []
        for index, sample in enumerate(samples):
            try:
                matrix = np.array(sample["head"], dtype=float)
                antennas = [float(v) for v in sample["antennas"]]
                body_yaw = float(sample.get("body_yaw", 0.0))
            except (KeyError, TypeError, ValueError) as exc:
                raise InvalidMove(f"{name}: sample {index} is malformed ({exc!r})") from exc
            if matrix.shape != (4, 4):
                raise InvalidMove(f"{name}: sample {index} head is not 4x4")
            if len(antennas) != 2:
                raise InvalidMove(f"{name}: sample {index} needs two antennas")
            frames.append(
                MoveFrame(
                    pose=matrix_to_pose(matrix),
                    antennas=AntennaPositions(left=antennas[0], right=antennas[1]),
                    body_yaw=body_yaw,
                )
            )
        return cls(name, description, times, frames)

    def sample(self, t: float) -> MoveFrame:
        """The move at ``t`` seconds, clamped to its first and last sample."""
        if t <= self.times[0]:
            return self.frames[0]
        if t >= self.times[-1]:
            return self.frames[-1]
        upper = int(np.searchsorted(self.times, t, side="right"))
        lower = upper - 1
        span = self.times[upper] - self.times[lower]
        frac = (t - self.times[lower]) / span
        a, b = self.frames[lower], self.frames[upper]
        return MoveFrame(
            pose=HeadPose(
                **{
                    field: _lerp(getattr(a.pose, field), getattr(b.pose, field), frac)
                    for field in ("x", "y", "z", "roll", "pitch", "yaw")
                }
            ),
            antennas=AntennaPositions(
                left=_lerp(a.antennas.left, b.antennas.left, frac),
                right=_lerp(a.antennas.right, b.antennas.right, frac),
            ),
            body_yaw=_lerp(a.body_yaw, b.body_yaw, frac),
        )
