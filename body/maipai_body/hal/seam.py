"""The HAL seam: the one boundary between the household runtime and a body.

Everything above this module names no vendor. Everything below it belongs
to one body profile under `body/bodies/`. A profile declares once what the
body has (`BodyProfile`); the typed actuator and sensor interfaces below are
what every profile implements, for both its real client and its fake.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from enum import StrEnum

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel

SEAM_VERSION = "0.1.0"


class GotoMethod(StrEnum):
    """Interpolation techniques a `goto` may use."""

    LINEAR = "linear"
    MINJERK = "minjerk"
    EASE_IN_OUT = "ease_in_out"
    CARTOON = "cartoon"


class HeadPose(BaseModel):
    """A 6-DoF head target: translation in metres, rotation in radians."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0


class Axis(BaseModel):
    """One declared limit on the profile, with where it came from.

    The profile is the sole place a numeric limit is written; everything
    else reads `min`/`max` from here.
    """

    name: str
    unit: str
    min: float
    max: float
    source: str
    date: str


class Channel(BaseModel):
    """One expressive channel the body declares."""

    name: str
    kind: str


class Sensor(BaseModel):
    """One sensor the body declares."""

    name: str
    kind: str


class BodyProfile(BaseModel):
    """The one declaration of what a body has."""

    id: str
    capabilities: list[str]
    axes: list[Axis]
    channels: list[Channel]
    sensors: list[Sensor]
    physical_cuts: list[str]
    speech_placement: str

    def axis(self, name: str) -> Axis:
        for a in self.axes:
            if a.name == name:
                return a
        raise KeyError(f"no axis named {name!r} on profile {self.id!r}")


class DoAReading(BaseModel):
    """Direction of arrival: angle in radians, and whether speech is present."""

    angle: float
    speech_detected: bool


class ImuReading(BaseModel):
    """One IMU sample. SI units; the quaternion is w-first."""

    accelerometer: tuple[float, float, float]
    gyroscope: tuple[float, float, float]
    quaternion: tuple[float, float, float, float]
    temperature_c: float


class StateFrame(BaseModel):
    """One state-feed sample, stamped on receipt by the client, never by the daemon."""

    monotonic_ns: int
    head_pose: HeadPose
    antennas: tuple[float, float]
    body_yaw: float
    doa: DoAReading | None = None


class HeadActuator(ABC):
    """The head, antennas and body yaw as one actuator behind the seam."""

    @abstractmethod
    def goto(
        self,
        pose: HeadPose | None,
        antennas: tuple[float, float] | None,
        body_yaw: float | None,
        duration_s: float,
        method: GotoMethod = GotoMethod.MINJERK,
    ) -> None:
        """Move to a target over `duration_s`.

        Raises `OutOfEnvelope` before anything reaches the daemon if the
        target falls outside the profile's axes; raises `BodyLost` if the
        connection is already lost or is lost while sending the command.
        """

    @abstractmethod
    def set_target(
        self,
        pose: HeadPose | None,
        antennas: tuple[float, float] | None,
        body_yaw: float | None,
    ) -> None:
        """Set a high-rate target the daemon's own control loop tracks."""

    @abstractmethod
    def hold(self) -> None:
        """Cancel trajectories and hold the current pose."""

    @abstractmethod
    def enable(self) -> None:
        """Enable the motors."""

    @abstractmethod
    def disable(self) -> None:
        """Disable the motors (limp)."""


class StateFeed(ABC):
    """The state feed: typed frames, each stamped on receipt."""

    @abstractmethod
    def frames(self) -> Iterator[StateFrame]:
        """Yield frames as they arrive. A live feed never returns on its own."""


class AudioIO(ABC):
    """Capture and playback, and the array's direction of arrival."""

    @abstractmethod
    def get_audio_sample(self) -> npt.NDArray[np.float32] | None:
        """One block of capture audio at 16 kHz float32, or None if none is ready."""

    @abstractmethod
    def push_audio_sample(self, data: npt.NDArray[np.float32]) -> None:
        """Play one block of float32 audio."""

    @abstractmethod
    def get_doa(self) -> DoAReading | None:
        """The array's current direction of arrival, or None if unavailable."""


class Camera(ABC):
    """A single capture owner for the body's camera."""

    @abstractmethod
    def get_frame(self) -> npt.NDArray[np.uint8] | None:
        """The latest camera frame (HxWx3 uint8), or None if unavailable."""


class Imu(ABC):
    """The body's inertial measurement unit, where one exists."""

    @abstractmethod
    def read(self) -> ImuReading | None:
        """The latest IMU reading, or None on a body with no IMU or a stale one."""
