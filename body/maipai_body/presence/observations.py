"""This body's own inputs to the presence funnel (design record section 6):
"a face is tracked" plus the array's direction of arrival and speech
flag, and the IMU's tip and freefall observations.
"""

from __future__ import annotations

import time
from typing import Protocol

from pydantic import BaseModel

from maipai_body.hal.seam import AudioIO, FaceTracker, Imu, ImuReading

from .safety import is_freefall, is_tipped


class PresenceSource(AudioIO, FaceTracker, Imu, Protocol):
    """Whatever a body client needs to answer for a presence read: DoA, a face target, the IMU."""


class PresenceObservation(BaseModel):
    """One stamped read of this body's presence-relevant sensors."""

    t_received_ns: int
    face_detected: bool
    face_x: float | None = None
    face_y: float | None = None
    doa_angle_rad: float | None = None
    speech_detected: bool = False
    tip_detected: bool = False
    freefall_detected: bool = False
    imu: ImuReading | None = None


def read_presence(client: PresenceSource) -> PresenceObservation:
    """Read one presence observation from a body client's face tracker, DoA and IMU."""
    face = client.get_face_target()
    doa = client.get_doa()
    imu = client.read()

    return PresenceObservation(
        t_received_ns=time.monotonic_ns(),
        face_detected=face.detected,
        face_x=face.x,
        face_y=face.y,
        doa_angle_rad=doa.angle_rad if doa is not None else None,
        speech_detected=doa.speech_detected if doa is not None else False,
        tip_detected=is_tipped(imu) if imu is not None else False,
        freefall_detected=is_freefall(imu) if imu is not None else False,
        imu=imu,
    )
