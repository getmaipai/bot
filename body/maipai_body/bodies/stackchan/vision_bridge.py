"""Host-side StackChan camera tracking and consent-gated face recognition."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from maipai_body.hal.seam import FaceTrackTarget, HeadPose
from maipai_body.vision.gallery import FaceVerdict
from maipai_body.vision.recognize import recognize_face


class StackChanVisionBridge:
    """Consume StackChan JPEG bytes in memory; identity is never used for motion."""

    def __init__(
        self,
        robot: Any,
        *,
        detector: Any,
        embedder: Any,
        gallery: Any,
        decode: Callable[[bytes], npt.NDArray[np.uint8]] | None = None,
        temp_dir: Path | None = None,
        consent_for_print: Callable[[str], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        frame_provider: Callable[[float], bytes | None] | None = None,
    ) -> None:
        self.robot = robot
        self.detector = detector
        self.embedder = embedder
        self.gallery = gallery
        self.decode = decode or _decode_jpeg
        self.temp_dir = temp_dir
        self.consent_for_print = consent_for_print or (lambda _: False)
        self.clock = clock
        self.frame_provider = frame_provider
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def track_stream_frame(self, *, deadline_s: float = 0.4) -> FaceTrackTarget:
        """Track from the latest streamed frame, discarding one past its deadline."""
        if not 0 < deadline_s <= 1.0:
            raise ValueError("tracking deadline must be over 0 and at most 1 second")
        started = self.clock()
        getter = self.frame_provider or getattr(self.robot.camera, "stream_frame", None)
        if getter is None:
            getter = getattr(self.robot, "camera_stream_frame", None)
        if getter is None:
            getter = self.robot._driver("camera").stream_frame
        if getter is None:
            return FaceTrackTarget(detected=False)
        frame_bytes = getter(deadline_s)
        if not frame_bytes or self.clock() - started > deadline_s:
            return FaceTrackTarget(detected=False)
        try:
            frame = self.decode(frame_bytes)
            if self.clock() - started > deadline_s:
                return FaceTrackTarget(detected=False)
            faces = self.detector.detect(frame)
            if not faces or self.clock() - started > deadline_s:
                return FaceTrackTarget(detected=False)
            x, y, width, height = faces[0].bbox
            frame_h, frame_w = frame.shape[:2]
            target = FaceTrackTarget(
                detected=True,
                x=float((x + width / 2) / frame_w),
                y=float((y + height / 2) / frame_h),
            )
            self._cancel_timer()
            pose = HeadPose(yaw=float((target.x - 0.5) * 0.35), pitch=float((0.5 - target.y) * 0.2))
            holder = "stackchan-vision"
            if self.robot.lease_holder != holder:
                self.robot.lease.acquire(priority="expression", holder=holder)
            try:
                self.robot.head.goto(pose=pose, duration_s=deadline_s)
            except Exception:
                self.robot.lease.release(holder=holder)
                raise
            timer = threading.Timer(deadline_s, self._hold_head)
            timer.daemon = True
            with self._lock:
                self._timer = timer
            timer.start()
            return target
        finally:
            del frame_bytes
            driver = self.robot._driver("camera") if hasattr(self.robot, "_driver") else None
            done = getattr(driver, "stream_frame_done", None)
            if callable(done):
                done()

    def set_print_consent(self, authorize: Callable[[str], bool]) -> None:
        """Install the print-store authorization check for child/teen profiles."""
        self.consent_for_print = authorize

    def track_once(self, *, deadline_s: float = 0.4) -> FaceTrackTarget:
        """Capture one frame and make a bounded anonymous head correction."""
        if not 0 < deadline_s <= 1.0:
            raise ValueError("tracking deadline must be over 0 and at most 1 second")
        frame_bytes = self.robot.camera.frame()
        if not frame_bytes:
            return FaceTrackTarget(detected=False)
        try:
            frame = self.decode(frame_bytes)
        finally:
            del frame_bytes
        faces = self.detector.detect(frame)
        if not faces:
            self._stop_expired_move()
            return FaceTrackTarget(detected=False)
        x, y, width, height = faces[0].bbox
        frame_h, frame_w = frame.shape[:2]
        target = FaceTrackTarget(
            detected=True,
            x=float((x + width / 2) / frame_w),
            y=float((y + height / 2) / frame_h),
        )
        self._cancel_timer()
        # The Robot head adapter clamps both angles against profile.py.
        pose = HeadPose(yaw=float((target.x - 0.5) * 0.35), pitch=float((0.5 - target.y) * 0.2))
        holder = "stackchan-vision"
        if self.robot.lease_holder != holder:
            self.robot.lease.acquire(priority="expression", holder=holder)
        try:
            self.robot.head.goto(pose=pose, duration_s=deadline_s)
        except Exception:
            self.robot.lease.release(holder=holder)
            raise
        timer = threading.Timer(deadline_s, self._hold_head)
        timer.daemon = True
        with self._lock:
            self._timer = timer
        timer.start()
        return target

    def recognize_once(
        self,
        *,
        person_id: str | None = None,
        age_group: str | None = None,
    ) -> FaceVerdict | None:
        """Return the gallery's tentative identity; only explicit consent enables hub stills."""
        if age_group in {"child", "teen"} and person_id and not self.consent_for_print(person_id):
            raise PermissionError(
                "face print consent is missing; complete the household consent flow"
            )
        frame_bytes = self.robot.camera.frame()
        if not frame_bytes:
            return None
        try:
            frame = self.decode(frame_bytes)
            return recognize_face(
                frame,
                detector=self.detector,
                embedder=self.embedder,
                gallery=self.gallery,
            )
        finally:
            del frame_bytes
            if "frame" in locals():
                del frame

    def send_consented_hub_still(
        self,
        deliver: Callable[[bytes], Any],
        *,
        authorize: Callable[[], bool],
    ) -> Any:
        """Send one captured JPEG only after the household still-image consent event."""
        if not authorize():
            raise PermissionError(
                "hub still consent is missing; complete the household consent flow"
            )
        frame_bytes = self.robot.camera.frame()
        if not frame_bytes:
            raise RuntimeError("StackChan camera returned no frame; retry the still capture")
        try:
            return deliver(frame_bytes)
        finally:
            del frame_bytes

    def close(self) -> None:
        self._cancel_timer()
        self._hold_head()

    def _stop_expired_move(self) -> None:
        with self._lock:
            timer = self._timer
            self._timer = None
        if timer is not None and timer.is_alive():
            self._hold_head()
            timer.cancel()

    def _cancel_timer(self) -> None:
        with self._lock:
            timer = self._timer
            self._timer = None
        if timer is not None:
            timer.cancel()

    def _hold_head(self) -> None:
        try:
            self.robot.head.hold()
        except Exception:
            # Robot records BodyLost and attempts its configured safe stop.
            pass
        finally:
            try:
                self.robot.lease.release(holder="stackchan-vision")
            except Exception:
                pass


def _decode_jpeg(data: bytes) -> npt.NDArray[np.uint8]:
    import cv2

    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("StackChan camera frame is not a decodable JPEG; capture another frame")
    return frame


__all__ = ["StackChanVisionBridge"]
