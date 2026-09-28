"""The HAL seam every body profile implements.

Nothing above this seam may learn a vendor's name (AGENTS.md;
``docs/dev/design-reachy-mini-2026-09-27.md`` section 2). A body is a
profile that declares its axes, channels, sensors and speech placement
once (``BodyProfile``), and the actuator, state feed, audio, camera and
IMU protocols below are the only way anything above the seam touches
hardware. A body's own client module (``maipai_body.bodies.<id>.client``)
is the one place that imports a vendor SDK; a fake
(``maipai_body.bodies.<id>.fake``) replays recorded fixtures through the
identical protocols so the same test suite runs against both.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Literal, Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel

SEAM_VERSION = "0.1.0"

InterpolationMethod = Literal["linear", "minjerk", "ease_in_out", "cartoon"]


class AxisLimit(BaseModel):
    """One axis's soft limit, with where the number came from.

    A profile is the one place these appear: BODY-04's calibration run
    for an owned build, a vendor's own documentation (or a live read of
    its daemon) for a purchased body. A test greps the package and fails
    if a numeric limit appears anywhere outside a profile module.
    """

    name: str
    unit: Literal["rad", "deg", "m"]
    min: float
    max: float
    source: str
    date: str  # ISO 8601 date the limit was recorded or last verified


class BodyProfile(BaseModel):
    """One body's declaration: what it has, never how it is driven.

    ``capabilities`` are ids from the body-capability vocabulary
    (commons' BODY-VOCAB-01 / RM-00, not yet landed in
    ``commons/spec/vocab/`` as of this profile's writing; see
    ``bodies/reachy_mini/profile.py`` for the reconciliation note).
    """

    id: str
    capabilities: list[str]
    axes: list[AxisLimit]
    channels: list[str]
    sensors: list[str]
    physical_cuts: list[str]
    speech_placement: Literal["pod", "robot"]

    def axis(self, name: str) -> AxisLimit:
        """Return the named axis's limit, or raise if this profile declares none."""
        for axis in self.axes:
            if axis.name == name:
                return axis
        raise KeyError(f"{self.id} declares no axis {name!r}")


class HeadPose(BaseModel):
    """A head pose in the seam's own units: meters and radians, never a vendor's matrix."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0


class AntennaPositions(BaseModel):
    """Antenna angles in radians. The seam's own canonical order is left, then right."""

    left: float
    right: float


class DirectionOfArrival(BaseModel):
    """A microphone array's direction-of-arrival reading."""

    angle_rad: float
    speech_detected: bool


class ImuReading(BaseModel):
    """One IMU sample."""

    accelerometer: tuple[float, float, float]
    gyroscope: tuple[float, float, float]
    quaternion: tuple[float, float, float, float]
    temperature_c: float


class FaceTrackTarget(BaseModel):
    """The latest face a body's own tracker sees. No identity, ever (design record section 6)."""

    detected: bool = False
    x: float | None = None
    y: float | None = None
    roll: float | None = None


class StateFrame(BaseModel):
    """One state-feed sample, typed and stamped on receipt.

    ``t_received_ns`` is ``time.monotonic_ns()`` taken by the client the
    instant the frame lands, never a vendor's own clock (``dev.md``
    section 5's "one clock" rule: the body and, later, the household
    runtime share ``CLOCK_MONOTONIC``).
    """

    t_received_ns: int
    seq: int
    head_pose: HeadPose | None = None
    antennas: AntennaPositions | None = None
    body_yaw: float | None = None
    doa: DirectionOfArrival | None = None

    @classmethod
    def stamped(cls, seq: int, **fields: object) -> StateFrame:
        """Build a frame stamped with the current monotonic clock reading."""
        return cls(t_received_ns=time.monotonic_ns(), seq=seq, **fields)  # type: ignore[arg-type]


@runtime_checkable
class HeadActuator(Protocol):
    """The one way anything above the seam moves a head."""

    def goto(
        self,
        pose: HeadPose | None = None,
        antennas: AntennaPositions | None = None,
        body_yaw: float | None = None,
        duration_s: float = 0.5,
        method: InterpolationMethod = "minjerk",
    ) -> None:
        """Move to a target over ``duration_s``, blocking until it lands.

        Raises ``OutOfEnvelope`` (checked against the profile's axes)
        before anything reaches the backend; raises ``BodyLost`` if the
        connection is gone.
        """
        ...

    def set_target(
        self,
        pose: HeadPose | None = None,
        antennas: AntennaPositions | None = None,
        body_yaw: float | None = None,
    ) -> None:
        """Set an immediate target for the backend's own control loop to track."""
        ...

    def hold(self) -> None:
        """Stop any in-flight trajectory and hold the present pose."""
        ...

    def enable(self) -> None:
        """Enable motor torque."""
        ...

    def disable(self) -> None:
        """Disable motor torque (limp)."""
        ...


@runtime_checkable
class StateFeed(Protocol):
    """A stream of typed, monotonically stamped state frames."""

    def __iter__(self) -> Iterator[StateFrame]: ...

    def close(self) -> None:
        """Stop the feed and release its connection."""
        ...


@runtime_checkable
class AudioIO(Protocol):
    """The audio calls a body exposes; G1/RM-04 is their real consumer.

    Every sample crossing this seam is float32: mono ``(n,)`` or
    multi-channel ``(n, channels)``, at whatever rate
    ``get_input_audio_samplerate``/``get_output_audio_samplerate`` name -
    never assumed to be 16 kHz here, even though every body built so far
    happens to run at that rate (RM-02's own envelope module makes the
    same mistake of a body-specific vendor fact leaking into body-
    agnostic code the seam itself is meant to prevent).
    """

    def start_recording(self) -> None:
        """Open the input stream; ``get_audio_sample`` returns nothing before this."""
        ...

    def stop_recording(self) -> None:
        """Close the input stream."""
        ...

    def get_audio_sample(self) -> npt.NDArray[np.float32] | None:
        """Return the next queued audio chunk, or ``None`` if none is available yet."""
        ...

    def get_input_audio_samplerate(self) -> int:
        """The input stream's sample rate in Hz."""
        ...

    def start_playing(self) -> None:
        """Open the output stream; call once before the first ``push_audio_sample``."""
        ...

    def push_audio_sample(self, data: npt.NDArray[np.float32]) -> None:
        """Push audio samples to the output device."""
        ...

    def stop_playing(self) -> None:
        """Close the output stream and flush whatever was queued."""
        ...

    def get_output_audio_samplerate(self) -> int:
        """The output stream's sample rate in Hz."""
        ...

    def get_doa(self) -> DirectionOfArrival | None:
        """Return the latest direction-of-arrival reading, or ``None``."""
        ...


@runtime_checkable
class Camera(Protocol):
    """The camera calls a body exposes. Checked 2026-09-28
    (`docs/dev/design-vision-still-image-2026-09-28.md`): RM-06 never
    calls either - it only ever consumes `FaceTracker`. `get_frame_jpeg()`
    is the still-image call's own capture path (`vision/capture.py`,
    its first named consumer): the vendor SDK already encodes JPEG
    itself (`media_manager.py`'s own `get_frame_jpeg()`), so nothing
    here re-encodes a raw frame - no new image dependency needed."""

    def get_frame(self) -> object | None:
        """Return the latest camera frame (BGR, ``(h, w, 3)`` uint8), or
        ``None`` if unavailable."""
        ...

    def get_frame_jpeg(self) -> bytes | None:
        """Return the latest camera frame already JPEG-encoded, or
        ``None`` if unavailable."""
        ...


@runtime_checkable
class Imu(Protocol):
    """The IMU read a body exposes; RM-06 is its real consumer."""

    def read(self) -> ImuReading | None:
        """Return the latest IMU reading, or ``None`` if unavailable."""
        ...


@runtime_checkable
class FaceTracker(Protocol):
    """A body's own visual head tracking; RM-06's presence funnel is its consumer.

    No identity is ever inferred from a tracked face (design record
    section 6): a body implementing this reports only "a face is
    tracked" and where, never who.
    """

    def enable_tracking(self, weight: float = 1.0) -> None:
        """Let tracking bias or own the head, per ``weight`` in ``[0, 1]``."""
        ...

    def disable_tracking(self) -> None:
        """Stop tracking (pauses detection, frees the head)."""
        ...

    def get_face_target(self) -> FaceTrackTarget:
        """Return the latest tracked face, or a target with ``detected=False``."""
        ...
