"""Replays recorded Reachy Mini fixtures through the same seam as the live client.

Loads ``fixtures/state_frames.jsonl`` (recorded by
``scripts/record_fixtures.py`` against a running simulator, in the sample
shape ``client.daemon_state_to_sample`` produces) and answers ``goto``,
``set_target``, ``hold``, ``enable``, ``disable`` and ``state_feed``
exactly as ``client.ReachyMiniClient`` does: the same envelope clamp
(``envelope.clamp_target``), the same ``BodyLost``/``OutOfEnvelope``
errors, nothing reaching the daemon (here, an in-memory log) when a
target is out of the envelope. The pytest suite in ``tests/`` runs
unmodified against either.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maipai_body.hal.errors import BodyLost
from maipai_body.hal.seam import (
    AntennaPositions,
    BodyProfile,
    DirectionOfArrival,
    HeadPose,
    ImuReading,
    InterpolationMethod,
    StateFrame,
)

from .envelope import clamp_target
from .profile import REACHY_MINI_PROFILE

FIXTURES_DIR = Path(__file__).parent / "fixtures"
STATE_FRAMES_PATH = FIXTURES_DIR / "state_frames.jsonl"


@dataclass
class SentCommand:
    """One command the fake recorded as "reaching the daemon"."""

    kind: str  # "goto" | "set_target" | "hold" | "enable" | "disable"
    pose: HeadPose | None = None
    antennas: AntennaPositions | None = None
    body_yaw: float | None = None
    duration_s: float | None = None
    method: InterpolationMethod | None = None


def load_recorded_samples() -> list[dict[str, Any]]:
    """Read ``state_frames.jsonl``, one sample dict per recorded frame."""
    if not STATE_FRAMES_PATH.exists():
        return []
    with STATE_FRAMES_PATH.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


class FakeReachyMiniClient:
    """Answers the HAL seam from recorded fixtures; never opens a socket."""

    def __init__(self, profile: BodyProfile = REACHY_MINI_PROFILE) -> None:
        self.profile = profile
        self._lost = False
        self.sent_commands: list[SentCommand] = []
        self.motors_enabled = True
        self._current_pose = HeadPose()
        self._current_antennas = AntennaPositions(left=0.0, right=0.0)
        self._current_body_yaw = 0.0

    # -- test control, not part of the seam --

    def simulate_disconnect(self) -> None:
        """Mark the fake lost, as a real client would after the daemon drops it."""
        self._lost = True

    # -- connection lifecycle --

    def _require_connected(self) -> None:
        if self._lost:
            raise BodyLost(f"{self.profile.id}: refusing a command after a prior connection loss")

    # -- HeadActuator --

    def goto(
        self,
        pose: HeadPose | None = None,
        antennas: AntennaPositions | None = None,
        body_yaw: float | None = None,
        duration_s: float = 0.5,
        method: InterpolationMethod = "minjerk",
    ) -> None:
        self._require_connected()
        clamp_target(self.profile, pose, antennas, body_yaw)
        self.sent_commands.append(
            SentCommand(
                kind="goto",
                pose=pose,
                antennas=antennas,
                body_yaw=body_yaw,
                duration_s=duration_s,
                method=method,
            )
        )
        self._apply(pose, antennas, body_yaw)

    def set_target(
        self,
        pose: HeadPose | None = None,
        antennas: AntennaPositions | None = None,
        body_yaw: float | None = None,
    ) -> None:
        self._require_connected()
        clamp_target(self.profile, pose, antennas, body_yaw)
        self.sent_commands.append(
            SentCommand(kind="set_target", pose=pose, antennas=antennas, body_yaw=body_yaw)
        )
        self._apply(pose, antennas, body_yaw)

    def hold(self) -> None:
        self._require_connected()
        self.sent_commands.append(
            SentCommand(
                kind="hold",
                pose=self._current_pose,
                antennas=self._current_antennas,
                body_yaw=self._current_body_yaw,
            )
        )

    def enable(self) -> None:
        self._require_connected()
        self.motors_enabled = True
        self.sent_commands.append(SentCommand(kind="enable"))

    def disable(self) -> None:
        self._require_connected()
        self.motors_enabled = False
        self.sent_commands.append(SentCommand(kind="disable"))

    def _apply(
        self, pose: HeadPose | None, antennas: AntennaPositions | None, body_yaw: float | None
    ) -> None:
        if pose is not None:
            self._current_pose = pose
        if antennas is not None:
            self._current_antennas = antennas
        if body_yaw is not None:
            self._current_body_yaw = body_yaw

    # -- AudioIO --

    def get_audio_sample(self) -> Any:
        self._require_connected()
        return None

    def push_audio_sample(self, data: Any) -> None:
        self._require_connected()

    def get_doa(self) -> DirectionOfArrival | None:
        self._require_connected()
        for sample in load_recorded_samples():
            if sample.get("doa") is not None:
                return DirectionOfArrival(**sample["doa"])
        return None

    # -- Camera --

    def get_frame(self) -> Any:
        self._require_connected()
        return None

    # -- Imu --

    def read(self) -> ImuReading | None:
        self._require_connected()
        return None

    # -- StateFeed --

    def state_feed(self, frequency: float = 10.0) -> FakeStateFeed:
        self._require_connected()
        return FakeStateFeed(self)


class FakeStateFeed:
    """Replays the recorded fixture's frames, stamped on "receipt" like the live feed."""

    def __init__(self, client: FakeReachyMiniClient) -> None:
        self._client = client
        self._samples = load_recorded_samples()
        self._index = 0

    def __iter__(self) -> Iterator[StateFrame]:
        return self

    def __next__(self) -> StateFrame:
        self._client._require_connected()
        if self._index >= len(self._samples):
            raise StopIteration
        sample = self._samples[self._index]
        frame = StateFrame.stamped(
            self._index,
            head_pose=HeadPose(**sample["head_pose"]) if sample.get("head_pose") else None,
            antennas=(AntennaPositions(**sample["antennas"]) if sample.get("antennas") else None),
            body_yaw=sample.get("body_yaw"),
            doa=DirectionOfArrival(**sample["doa"]) if sample.get("doa") else None,
        )
        self._index += 1
        return frame

    def close(self) -> None:
        pass
