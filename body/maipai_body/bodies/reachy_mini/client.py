"""The reachy-mini SDK behind the HAL seam.

Actuation (`goto`, `set_target`, `hold`, `enable`, `disable`) goes through
the `reachy_mini` SDK's `ReachyMini` class. The state feed is its own
WebSocket connection to `ws://<host>:<port>/api/state/ws/full`: the SDK
exposes no streaming call of its own for it, and the design record names
that route directly as the encoder stand-in.

Every command clamps against `profile.PROFILE`'s axes before it reaches
the daemon (`envelope.check_envelope`); the daemon's own clamp is the
second line, never the first. A connection loss anywhere raises
`BodyLost` once, and the body that raised it refuses every further
command until something calls `reconnect()`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import requests
import websockets.exceptions as ws_exceptions
import websockets.sync.client as ws_sync
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

from maipai_body.hal.seam import (
    AudioIO,
    BodyProfile,
    Camera,
    DoAReading,
    GotoMethod,
    HeadActuator,
    HeadPose,
    Imu,
    ImuReading,
    StateFeed,
    StateFrame,
)

from .connection import ConnectionState
from .envelope import check_envelope_with_defaults
from .profile import PROFILE
from .wire import frame_from_full_state_payload

_DAEMON_ERRORS = (ConnectionError, TimeoutError)


def _to_head_matrix(pose: HeadPose | None):
    if pose is None:
        return None
    return create_head_pose(pose.x, pose.y, pose.z, pose.roll, pose.pitch, pose.yaw, degrees=False)


class ReachyMiniHeadActuator(HeadActuator):
    def __init__(self, sdk: ReachyMini, state: ConnectionState, base_url: str) -> None:
        self._sdk = sdk
        self._state = state
        self._base_url = base_url
        self._last_head_yaw = 0.0
        self._last_body_yaw = 0.0

    def _check_envelope(self, pose, antennas, body_yaw) -> None:
        check_envelope_with_defaults(
            pose, antennas, body_yaw, self._last_head_yaw, self._last_body_yaw
        )

    def goto(
        self,
        pose,
        antennas,
        body_yaw,
        duration_s,
        method=GotoMethod.MINJERK,
    ) -> None:
        self._state.check()
        self._check_envelope(pose, antennas, body_yaw)
        try:
            self._sdk.goto_target(
                head=_to_head_matrix(pose),
                antennas=list(antennas) if antennas is not None else None,
                duration=duration_s,
                method=method.value,
                body_yaw=body_yaw,
            )
        except _DAEMON_ERRORS as exc:
            raise self._state.mark_lost(str(exc)) from exc
        if pose is not None:
            self._last_head_yaw = pose.yaw
        if body_yaw is not None:
            self._last_body_yaw = body_yaw

    def set_target(self, pose, antennas, body_yaw) -> None:
        self._state.check()
        self._check_envelope(pose, antennas, body_yaw)
        try:
            self._sdk.set_target(
                head=_to_head_matrix(pose),
                antennas=list(antennas) if antennas is not None else None,
                body_yaw=body_yaw,
            )
        except _DAEMON_ERRORS as exc:
            raise self._state.mark_lost(str(exc)) from exc
        if pose is not None:
            self._last_head_yaw = pose.yaw
        if body_yaw is not None:
            self._last_body_yaw = body_yaw

    def hold(self) -> None:
        self._state.check()
        try:
            # Read the daemon's own present-state routes (xyzrpy directly,
            # no matrix decomposition) so the frozen target and this
            # actuator's own yaw tracking agree with what is actually held.
            current_pose = requests.get(
                f"{self._base_url}/api/state/present_head_pose", timeout=5
            ).json()
            _, antenna_positions = self._sdk.get_current_joint_positions()
            current_body_yaw = requests.get(
                f"{self._base_url}/api/state/present_body_yaw", timeout=5
            ).json()
            head_matrix = create_head_pose(
                current_pose["x"],
                current_pose["y"],
                current_pose["z"],
                current_pose["roll"],
                current_pose["pitch"],
                current_pose["yaw"],
                degrees=False,
            )
            self._sdk.set_target_head_pose(head_matrix)
            self._sdk.set_target_antenna_joint_positions(list(antenna_positions))
            self._sdk.set_target_body_yaw(current_body_yaw)
        except (*_DAEMON_ERRORS, requests.RequestException) as exc:
            raise self._state.mark_lost(str(exc)) from exc
        self._last_head_yaw = current_pose["yaw"]
        self._last_body_yaw = current_body_yaw

    def enable(self) -> None:
        self._state.check()
        try:
            self._sdk.enable_motors()
        except _DAEMON_ERRORS as exc:
            raise self._state.mark_lost(str(exc)) from exc

    def disable(self) -> None:
        self._state.check()
        try:
            self._sdk.disable_motors()
        except _DAEMON_ERRORS as exc:
            raise self._state.mark_lost(str(exc)) from exc


class ReachyMiniStateFeed(StateFeed):
    def __init__(
        self, host: str, port: int, state: ConnectionState, frequency: float = 20.0
    ) -> None:
        self._url = (
            f"ws://{host}:{port}/api/state/ws/full"
            f"?frequency={frequency}&with_doa=true&with_imu=true"
        )
        self._state = state

    def frames(self) -> Iterator[StateFrame]:
        self._state.check()
        try:
            with ws_sync.connect(self._url, open_timeout=5) as conn:
                while True:
                    message = conn.recv()
                    stamp = time.monotonic_ns()
                    yield frame_from_full_state_payload(json.loads(message), stamp)
        except (ws_exceptions.WebSocketException, OSError, TimeoutError) as exc:
            raise self._state.mark_lost(str(exc)) from exc


class ReachyMiniAudioIO(AudioIO):
    def __init__(self, sdk: ReachyMini, state: ConnectionState) -> None:
        self._sdk = sdk
        self._state = state

    def get_audio_sample(self) -> npt.NDArray[np.float32] | None:
        self._state.check()
        try:
            return self._sdk.media.get_audio_sample()
        except _DAEMON_ERRORS as exc:
            raise self._state.mark_lost(str(exc)) from exc

    def push_audio_sample(self, data: npt.NDArray[np.float32]) -> None:
        self._state.check()
        try:
            self._sdk.media.push_audio_sample(data)
        except _DAEMON_ERRORS as exc:
            raise self._state.mark_lost(str(exc)) from exc

    def get_doa(self) -> DoAReading | None:
        self._state.check()
        try:
            result = self._sdk.media.get_DoA()
        except _DAEMON_ERRORS as exc:
            raise self._state.mark_lost(str(exc)) from exc
        if result is None:
            return None
        angle, speech_detected = result
        return DoAReading(angle=angle, speech_detected=speech_detected)


class ReachyMiniCamera(Camera):
    def __init__(self, sdk: ReachyMini, state: ConnectionState) -> None:
        self._sdk = sdk
        self._state = state

    def get_frame(self) -> npt.NDArray[np.uint8] | None:
        self._state.check()
        try:
            return self._sdk.media.get_frame()
        except _DAEMON_ERRORS as exc:
            raise self._state.mark_lost(str(exc)) from exc


class ReachyMiniImu(Imu):
    def __init__(self, sdk: ReachyMini, state: ConnectionState) -> None:
        self._sdk = sdk
        self._state = state

    def read(self) -> ImuReading | None:
        self._state.check()
        try:
            data = self._sdk.imu
        except _DAEMON_ERRORS as exc:
            raise self._state.mark_lost(str(exc)) from exc
        if data is None:
            return None
        return ImuReading(
            accelerometer=tuple(data["accelerometer"]),
            gyroscope=tuple(data["gyroscope"]),
            quaternion=tuple(data["quaternion"]),
            temperature_c=data["temperature"],
        )


@dataclass
class ReachyMiniBody:
    """One connected Reachy Mini body: the profile plus every seam part."""

    profile: BodyProfile
    head: HeadActuator
    state_feed: StateFeed
    audio: AudioIO
    camera: Camera
    imu: Imu
    sdk: ReachyMini
    connection: ConnectionState
    owns_sdk: bool = True

    def reconnect(self) -> None:
        """Clear the lost flag once the daemon connection is re-established."""
        self.connection.clear()

    def close(self) -> None:
        """Disconnect the SDK, unless something else owns its lifecycle.

        `wrap_connected_sdk` sets `owns_sdk=False`: the daemon's own app
        framework connected that `ReachyMini` instance and tears it down
        itself when `run()` returns, so this body must not double-close it.
        """
        if self.owns_sdk:
            self.sdk.__exit__(None, None, None)


def _wire_seam(sdk: ReachyMini, host: str, port: int, owns_sdk: bool) -> ReachyMiniBody:
    state = ConnectionState()
    return ReachyMiniBody(
        profile=PROFILE,
        head=ReachyMiniHeadActuator(sdk, state, base_url=f"http://{host}:{port}"),
        state_feed=ReachyMiniStateFeed(host, port, state),
        audio=ReachyMiniAudioIO(sdk, state),
        camera=ReachyMiniCamera(sdk, state),
        imu=ReachyMiniImu(sdk, state),
        sdk=sdk,
        connection=state,
        owns_sdk=owns_sdk,
    )


def build_live_body(host: str = "localhost", port: int = 8000) -> ReachyMiniBody:
    """Connect to a running reachy-mini-daemon and wire up the seam."""
    sdk = ReachyMini(host=host, port=port, spawn_daemon=False)
    return _wire_seam(sdk, host, port, owns_sdk=True)


def wrap_connected_sdk(
    sdk: ReachyMini, host: str = "localhost", port: int = 8000
) -> ReachyMiniBody:
    """Wire the seam around an already-connected `ReachyMini` instance.

    Used by the app entry point (`app.py`): the daemon's own
    `ReachyMiniApp.wrapped_run` constructs and connects the SDK object
    before handing it to `run()`, so this body never closes it.
    """
    return _wire_seam(sdk, host, port, owns_sdk=False)
