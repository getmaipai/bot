"""The Reachy Mini fake: replays recorded fixtures through the same seam.

`build_fake_body()` returns an object with the same shape as
`client.build_live_body()`: the same profile, the same `HeadActuator`,
`StateFeed`, `AudioIO`, `Camera` and `Imu` interfaces, so the deterministic
suite in `tests/` runs unchanged against either. State frames come from
`fixtures/state_frames.jsonl`, recorded against the simulator by
`scripts/record_fixtures.py`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt

from maipai_body.hal.seam import (
    AudioIO,
    BodyProfile,
    Camera,
    DoAReading,
    GotoMethod,
    HeadActuator,
    Imu,
    ImuReading,
    StateFeed,
    StateFrame,
)

from .connection import ConnectionState
from .envelope import check_envelope_with_defaults
from .profile import PROFILE
from .wire import frame_from_full_state_payload

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_recorded_frames(path: Path) -> list[dict]:
    frames = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                frames.append(json.loads(line))
    if not frames:
        raise ValueError(f"no recorded frames in {path}")
    return frames


@dataclass
class _FakeState:
    """The shared state a fake's actuator and its feed both read and set."""

    connection: ConnectionState = field(default_factory=ConnectionState)
    held: bool = False
    last_head_yaw: float = 0.0
    last_body_yaw: float = 0.0
    frame_index: int = 0
    last_goto: dict | None = None
    last_set_target: dict | None = None


class FakeHeadActuator(HeadActuator):
    def __init__(self, state: _FakeState) -> None:
        self._state = state

    def _check_envelope(self, pose, antennas, body_yaw) -> None:
        check_envelope_with_defaults(
            pose, antennas, body_yaw, self._state.last_head_yaw, self._state.last_body_yaw
        )

    def goto(self, pose, antennas, body_yaw, duration_s, method=GotoMethod.MINJERK) -> None:
        self._state.connection.check()
        self._check_envelope(pose, antennas, body_yaw)
        self._state.last_goto = {
            "pose": pose,
            "antennas": antennas,
            "body_yaw": body_yaw,
            "duration_s": duration_s,
            "method": method,
        }
        self._state.held = False
        if pose is not None:
            self._state.last_head_yaw = pose.yaw
        if body_yaw is not None:
            self._state.last_body_yaw = body_yaw

    def set_target(self, pose, antennas, body_yaw) -> None:
        self._state.connection.check()
        self._check_envelope(pose, antennas, body_yaw)
        self._state.last_set_target = {"pose": pose, "antennas": antennas, "body_yaw": body_yaw}
        if pose is not None:
            self._state.last_head_yaw = pose.yaw
        if body_yaw is not None:
            self._state.last_body_yaw = body_yaw

    def hold(self) -> None:
        self._state.connection.check()
        self._state.held = True

    def enable(self) -> None:
        self._state.connection.check()

    def disable(self) -> None:
        self._state.connection.check()


class FakeStateFeed(StateFeed):
    def __init__(self, state: _FakeState, recorded: list[dict]) -> None:
        self._state = state
        self._recorded = recorded

    def frames(self) -> Iterator[StateFrame]:
        self._state.connection.check()
        last_stamp = 0
        last_frame: StateFrame | None = None
        while True:
            self._state.connection.check()
            if self._state.held and last_frame is not None:
                base = last_frame
            else:
                raw = self._recorded[self._state.frame_index % len(self._recorded)]
                self._state.frame_index += 1
                base = frame_from_full_state_payload(raw, monotonic_ns=0)
            stamp = time.monotonic_ns()
            if stamp <= last_stamp:
                stamp = last_stamp + 1
            last_stamp = stamp
            last_frame = base.model_copy(update={"monotonic_ns": stamp})
            yield last_frame


class FakeAudioIO(AudioIO):
    def __init__(self, state: _FakeState) -> None:
        self._state = state

    def get_audio_sample(self) -> npt.NDArray[np.float32] | None:
        self._state.connection.check()
        return None

    def push_audio_sample(self, data: npt.NDArray[np.float32]) -> None:
        self._state.connection.check()

    def get_doa(self) -> DoAReading | None:
        self._state.connection.check()
        return None


class FakeCamera(Camera):
    def __init__(self, state: _FakeState) -> None:
        self._state = state

    def get_frame(self) -> npt.NDArray[np.uint8] | None:
        self._state.connection.check()
        return None


class FakeImu(Imu):
    def __init__(self, state: _FakeState) -> None:
        self._state = state

    def read(self) -> ImuReading | None:
        self._state.connection.check()
        return None


@dataclass
class FakeReachyMiniBody:
    """The fake's version of `client.ReachyMiniBody`: the same shape, no daemon."""

    profile: BodyProfile
    head: HeadActuator
    state_feed: StateFeed
    audio: AudioIO
    camera: Camera
    imu: Imu
    state: _FakeState = field(repr=False)

    def simulate_connection_loss(self) -> None:
        """Test hook: mark the connection lost, as a real one would raise it."""
        self.state.connection.lost = True

    def reconnect(self) -> None:
        self.state.connection.clear()

    def close(self) -> None:
        pass


def build_fake_body(fixtures_dir: Path = _FIXTURES_DIR) -> FakeReachyMiniBody:
    """Build a fake wired to the same seam, replaying `fixtures_dir`'s recording."""
    recorded = _load_recorded_frames(fixtures_dir / "state_frames.jsonl")
    state = _FakeState()
    return FakeReachyMiniBody(
        profile=PROFILE,
        head=FakeHeadActuator(state),
        state_feed=FakeStateFeed(state, recorded),
        audio=FakeAudioIO(state),
        camera=FakeCamera(state),
        imu=FakeImu(state),
        state=state,
    )
