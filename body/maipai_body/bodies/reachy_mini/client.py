"""The Reachy Mini SDK behind the HAL seam.

The one file in this profile that imports the vendor SDK
(``reachy_mini``, PyPI, Apache-2.0). It clamps every target against
``profile.py``'s axes before anything reaches the daemon; the daemon's
own clamp is the second line, never the first. It converts the seam's
own units (radians; ``HeadPose``; left-then-right ``AntennaPositions``)
to and from the SDK's 4x4 pose matrices and its command payloads'
``[right, left]`` antenna order (``reachy_mini.io.protocol.SetAntennasCmd``
and ``GotoTaskRequest`` both document that order; the daemon's own state
read path, ``present_antenna_joint_positions``, documents the opposite
order, ``(left, right)``: an unreconciled inconsistency in the vendor's
own docs, so this client treats every *read* as ``(left, right)`` and
every *write* as ``[right, left]``, converting explicitly at each
boundary rather than guessing once). It raises ``BodyLost`` once on any
connection loss and refuses every further call until a fresh client is
built.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, NoReturn

import numpy as np
import requests
from reachy_mini import ReachyMini
from reachy_mini.io.protocol import StopMoveCmd
from reachy_mini.utils.rotation import Rotation
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection
from websockets.sync.client import connect as ws_connect

from maipai_body.hal.errors import BodyLost
from maipai_body.hal.seam import (
    AntennaPositions,
    BodyProfile,
    DirectionOfArrival,
    FaceTrackTarget,
    HeadPose,
    ImuReading,
    InterpolationMethod,
    StateFrame,
)

from .envelope import clamp_target
from .profile import REACHY_MINI_PROFILE

# The SDK's own websocket client (reachy_mini.io.ws_client.WSClient) raises
# the builtin ConnectionError only when its own liveness flag has already
# caught up with a lost socket; a socket that closes out from under it (the
# daemon restarting, a network drop) surfaces as websockets' own
# ConnectionClosed first, verified live against the running simulator by
# closing its connection directly and reading the exception it actually
# raises. Both are "the connection to the backend is gone" here.
_CONNECTION_LOST_ERRORS = (ConnectionError, TimeoutError, ConnectionClosed)


def _pose_to_matrix(pose: HeadPose) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, 3] = [pose.x, pose.y, pose.z]
    matrix[:3, :3] = Rotation.from_euler("xyz", [pose.roll, pose.pitch, pose.yaw]).as_matrix()
    return matrix


class ReachyMiniClient:
    """The Reachy Mini SDK behind the seam's HeadActuator, AudioIO, Camera and Imu protocols."""

    def __init__(
        self,
        profile: BodyProfile = REACHY_MINI_PROFILE,
        *,
        host: str = "localhost",
        port: int = 8000,
        connection_mode: str = "auto",
        reachy: ReachyMini | None = None,
    ) -> None:
        self.profile = profile
        self._lost = False
        self._reachy = reachy or ReachyMini(host=host, port=port, connection_mode=connection_mode)

    # -- connection lifecycle --

    def _require_connected(self) -> None:
        if self._lost:
            raise BodyLost(f"{self.profile.id}: refusing a command after a prior connection loss")

    def _mark_lost(self, error: Exception) -> NoReturn:
        self._lost = True
        raise BodyLost(f"{self.profile.id}: lost connection to the daemon: {error}") from error

    def disconnect(self) -> None:
        self._lost = True
        self._reachy.client.disconnect()

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
        try:
            self._reachy.goto_target(
                head=_pose_to_matrix(pose) if pose is not None else None,
                antennas=[antennas.right, antennas.left] if antennas is not None else None,
                duration=duration_s,
                method=method,
                body_yaw=body_yaw,
            )
        except _CONNECTION_LOST_ERRORS as error:
            self._mark_lost(error)

    def set_target(
        self,
        pose: HeadPose | None = None,
        antennas: AntennaPositions | None = None,
        body_yaw: float | None = None,
    ) -> None:
        self._require_connected()
        clamp_target(self.profile, pose, antennas, body_yaw)
        try:
            self._reachy.set_target(
                head=_pose_to_matrix(pose) if pose is not None else None,
                antennas=[antennas.right, antennas.left] if antennas is not None else None,
                body_yaw=body_yaw,
            )
        except _CONNECTION_LOST_ERRORS as error:
            self._mark_lost(error)

    def hold(self) -> None:
        """Cancel whatever is in flight, then re-issue the present pose as an
        immediate target so nothing drifts once it's cancelled.

        A code review (2026-09-27) found this only did the second half:
        without ``StopMoveCmd`` first, a `goto` task keeps writing
        interpolated targets until its own duration elapses
        (``reachy_mini/daemon/backend/abstract.py``'s goto loop polls the
        stop flag that command sets), so "stop" during a goto was a fight
        the goto won until it finished. ``StopMoveCmd`` is acked
        idempotently (``stopped: false`` when nothing was running, never an
        error), so sending it unconditionally is safe.
        """
        self._require_connected()
        try:
            self._reachy.client.send_command(StopMoveCmd())
        except _CONNECTION_LOST_ERRORS as error:
            self._mark_lost(error)  # NoReturn: raises BodyLost
        base = self._reachy._daemon_http_url
        try:
            pose = HeadPose(**requests.get(f"{base}/api/state/present_head_pose", timeout=5).json())
            left, right = requests.get(
                f"{base}/api/state/present_antenna_joint_positions", timeout=5
            ).json()
            body_yaw = float(requests.get(f"{base}/api/state/present_body_yaw", timeout=5).json())
        except (*_CONNECTION_LOST_ERRORS, requests.RequestException) as error:
            self._mark_lost(error)  # NoReturn: raises BodyLost
        self.set_target(
            pose=pose, antennas=AntennaPositions(left=left, right=right), body_yaw=body_yaw
        )

    def enable(self) -> None:
        self._require_connected()
        try:
            self._reachy.enable_motors()
        except _CONNECTION_LOST_ERRORS as error:
            self._mark_lost(error)

    def disable(self) -> None:
        self._require_connected()
        try:
            self._reachy.disable_motors()
        except _CONNECTION_LOST_ERRORS as error:
            self._mark_lost(error)

    # -- AudioIO --

    def get_audio_sample(self) -> Any:
        self._require_connected()
        return self._reachy.media.get_audio_sample()

    def push_audio_sample(self, data: Any) -> None:
        self._require_connected()
        self._reachy.media.push_audio_sample(data)

    def get_doa(self) -> DirectionOfArrival | None:
        self._require_connected()
        reading = self._reachy.media.get_DoA()
        if reading is None:
            return None
        angle, speech_detected = reading
        return DirectionOfArrival(angle_rad=angle, speech_detected=speech_detected)

    # -- Camera --

    def get_frame(self) -> Any:
        self._require_connected()
        return self._reachy.media.get_frame()

    # -- Imu --

    def read(self) -> ImuReading | None:
        self._require_connected()
        base = self._reachy._daemon_http_url
        try:
            response = requests.get(f"{base}/api/state/imu", timeout=5)
            response.raise_for_status()
            data = response.json()
        except (*_CONNECTION_LOST_ERRORS, requests.RequestException) as error:
            self._mark_lost(error)
        if data is None:
            return None
        return ImuReading(
            accelerometer=tuple(data["accelerometer"]),
            gyroscope=tuple(data["gyroscope"]),
            quaternion=tuple(data["quaternion"]),
            temperature_c=data["temperature"],
        )

    # -- FaceTracker --

    def enable_tracking(self, weight: float = 1.0) -> None:
        self._require_connected()
        try:
            self._reachy.start_head_tracking(weight)
        except _CONNECTION_LOST_ERRORS as error:
            self._mark_lost(error)

    def disable_tracking(self) -> None:
        self._require_connected()
        try:
            self._reachy.stop_head_tracking()
        except _CONNECTION_LOST_ERRORS as error:
            self._mark_lost(error)

    def get_face_target(self) -> FaceTrackTarget:
        self._require_connected()
        try:
            # A short wait, not wait=False: the SDK's own get_status()
            # asserts a status has already arrived when it does not wait,
            # which raises AssertionError on a fresh connection with no
            # status yet. TimeoutError here means "nothing observed in
            # time", not a lost connection, so it is caught on its own
            # rather than folded into _CONNECTION_LOST_ERRORS.
            target = self._reachy.get_tracked_face(wait=True, timeout=1.0)
        except TimeoutError:
            return FaceTrackTarget(detected=False)
        except _CONNECTION_LOST_ERRORS as error:
            self._mark_lost(error)
        return FaceTrackTarget(detected=target.detected, x=target.x, y=target.y, roll=target.roll)

    # -- StateFeed --

    def state_feed(self, frequency: float = 10.0) -> ReachyMiniStateFeed:
        return ReachyMiniStateFeed(self, frequency=frequency)


class ReachyMiniStateFeed:
    """Iterates typed ``StateFrame`` objects from ``ws://.../api/state/ws/full``."""

    def __init__(self, client: ReachyMiniClient, *, frequency: float = 10.0) -> None:
        self._client = client
        self._seq = 0
        reachy = client._reachy
        url = (
            f"ws://{reachy.client.host}:{reachy.client.port}/api/state/ws/full"
            f"?frequency={frequency}&with_doa=true"
        )
        try:
            self._ws: ClientConnection = ws_connect(url, open_timeout=5)
        except OSError as error:
            client._mark_lost(error)

    def __iter__(self) -> Iterator[StateFrame]:
        return self

    def __next__(self) -> StateFrame:
        self._client._require_connected()
        try:
            message = self._ws.recv()
        except Exception as error:  # websockets' own ConnectionClosed and friends
            self._client._mark_lost(error)
        data = json.loads(message)
        frame = _daemon_state_to_frame(self._seq, data)
        self._seq += 1
        return frame

    def close(self) -> None:
        self._ws.close()


def daemon_state_to_sample(data: dict[str, Any]) -> dict[str, Any]:
    """Map one ``FullState`` JSON payload to the seam's own sample shape.

    Used both to build a live ``StateFrame`` on receipt and, by
    ``scripts/record_fixtures.py``, to write ``state_frames.jsonl`` in the
    exact shape ``fake.py`` replays. ``antennas_position`` on this read
    path is documented ``(left, right)``
    (``reachy_mini.daemon.app.routers.state`` docstrings), the seam's own
    canonical order, so no reordering happens here.
    """
    head_pose = HeadPose(**data["head_pose"]) if data.get("head_pose") is not None else None
    antennas = None
    if data.get("antennas_position") is not None:
        left, right = data["antennas_position"]
        antennas = AntennaPositions(left=left, right=right)
    doa = None
    if data.get("doa") is not None:
        doa = DirectionOfArrival(
            angle_rad=data["doa"]["angle"], speech_detected=data["doa"]["speech_detected"]
        )
    return {
        "head_pose": head_pose.model_dump(mode="json") if head_pose is not None else None,
        "antennas": antennas.model_dump(mode="json") if antennas is not None else None,
        "body_yaw": data.get("body_yaw"),
        "doa": doa.model_dump(mode="json") if doa is not None else None,
    }


def _daemon_state_to_frame(seq: int, data: dict[str, Any]) -> StateFrame:
    """Map one ``FullState`` JSON payload to a stamped, typed ``StateFrame``."""
    sample = daemon_state_to_sample(data)
    return StateFrame.stamped(
        seq,
        head_pose=HeadPose(**sample["head_pose"]) if sample["head_pose"] is not None else None,
        antennas=(
            AntennaPositions(**sample["antennas"]) if sample["antennas"] is not None else None
        ),
        body_yaw=sample["body_yaw"],
        doa=DirectionOfArrival(**sample["doa"]) if sample["doa"] is not None else None,
    )
