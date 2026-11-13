"""Host-side StackChan camera tracking and consent-gated face recognition."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from maipai_body.bodies.stackchan.frame_check import FrameCheck
from maipai_body.hal.seam import FaceTrackTarget, HeadPose
from maipai_body.vision.gallery import FaceVerdict


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
        look_detector: Any = None,
    ) -> None:
        self.robot = robot
        self.detector = detector
        # The robot's own fast Look pass (vision/look_fast.py): people and household things on
        # the same decoded frame. Optional; without it only faces are known.
        self.look_detector = look_detector
        self.embedder = embedder
        self.gallery = gallery
        self.decode = decode or _decode_jpeg
        self.temp_dir = temp_dir
        self.consent_for_print = consent_for_print or (lambda _: False)
        self.clock = clock
        self.frame_provider = frame_provider
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self.frame_check = FrameCheck()
        # The newest streamed frame, in memory only: (jpeg, when, face count, light level). It is
        # replaced by the next look, and cleared once it has been posted to Home (vision_post.py).
        self._latest_look: tuple[bytes, float, int, float, Any] | None = None
        # Movement between this look and the one before (presence_watch.motion_fraction): the share
        # of the picture that changed, and when something last moved. A second presence signal
        # beside faces, for a person whose face is out of the picture (an arm at the desk).
        self.last_motion: float = 0.0
        self._last_motion_at: float | None = None
        self._last_thumb: Any = None  # the thumbnail of the look before, for the next comparison
        # The fast pass of the newest look: the LookResult objects (labels, counts, boxes) and the
        # person boxes, each with the frame's arrival time. Scalars only, replaced by the next look.
        self._latest_objects: tuple[list[dict], float] | None = None
        self._latest_people: tuple[list[Any], float] | None = None
        self._last_person: tuple[Any, float] | None = None  # the largest box last seen, when
        self._last_person_at: float | None = None
        self.last_look_ms: float | None = None  # how long the Look detector took on the last look
        self.last_best_person = 0.0  # the detector's best person score on the last look
        self.last_pose_deg: tuple[float, float] | None = None  # yaw, pitch up: the last follow

    def track_stream_frame(
        self, *, deadline_s: float = 0.4, may_move: Callable[[], bool] | None = None
    ) -> FaceTrackTarget:
        """Track from the latest streamed frame, discarding one past its deadline.

        ``may_move`` is asked just before the head would follow the face; when it says no the
        face is still reported (the room is occupied) but the head stays where it is."""
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
            from maipai_body.bodies.stackchan.presence_watch import MOTION_FRACTION, motion_fraction
            from maipai_body.bodies.stackchan.vision_post import scene_luma, thumbnail

            frame_at = self._frame_arrival() or self.clock()
            self._fast_pass(frame, frame_at)
            thumb = thumbnail(frame)
            previous = self._latest_look[4] if self._latest_look is not None else self._last_thumb
            self.last_motion = motion_fraction(previous, thumb)
            if self.last_motion >= MOTION_FRACTION:
                self._last_motion_at = self.clock()
            self._last_thumb = thumb
            self._latest_look = (
                bytes(frame_bytes),
                frame_at,
                len(faces),
                scene_luma(frame),
                thumb,
            )
            if not faces:
                self.frame_check.note(self.detector, frame, len(frame_bytes))
            if not faces or self.clock() - started > deadline_s:
                return FaceTrackTarget(detected=False)
            x, y, width, height = faces[0].bbox
            frame_h, frame_w = frame.shape[:2]
            target = FaceTrackTarget(
                detected=True,
                x=float((x + width / 2) / frame_w),
                y=float((y + height / 2) / frame_h),
            )
            if may_move is not None and not may_move():
                return target
            self._cancel_timer()
            pose = follow_pose(target)
            self.last_pose_deg = follow_pose_degrees(target)
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

    def _frame_arrival(self) -> float | None:
        """When the frame just popped arrived from the unit (the camera driver keeps it)."""
        driver = self.robot._driver("camera") if hasattr(self.robot, "_driver") else None
        at = getattr(driver, "last_frame_at", None)
        return float(at) if isinstance(at, (int, float)) else None

    def _fast_pass(self, frame: npt.NDArray[np.uint8], frame_at: float) -> None:
        """Run the Look detector on the decoded frame; keep its objects and person boxes."""
        detector = self.look_detector
        if detector is None:
            return
        from maipai_body.bodies.stackchan.person_tracker import PersonBox
        from maipai_body.vision.look_fast import PERSON, objects_of

        try:
            found = detector.detect(frame)
        except Exception:
            self.last_look_ms = None
            return
        self.last_look_ms = getattr(detector, "last_ms", None)
        self.last_best_person = float(getattr(detector, "last_best_person", 0.0) or 0.0)
        people = [
            PersonBox(d.box[0], d.box[1], d.box[2], d.box[3], d.score)
            for d in found
            if d.label == PERSON
        ]
        self._latest_objects = (objects_of(found), frame_at)
        self._latest_people = (people, frame_at)
        if people:
            self._last_person_at = frame_at
            self._last_person = (max(people, key=lambda b: b.area), frame_at)

    def people(self, *, max_age_s: float) -> list[Any]:
        """The person boxes of the newest look if it is young enough (empty otherwise)."""
        latest = self._latest_people
        if latest is None or self.clock() - latest[1] > max_age_s:
            return []
        return list(latest[0])

    def last_person(self, *, max_age_s: float) -> Any | None:
        """The largest person box seen within ``max_age_s``, even if a newer look had none."""
        last = self._last_person
        if last is None or self.clock() - last[1] > max_age_s:
            return None
        return last[0]

    def look_at(self) -> float | None:
        """When the newest look's frame arrived (monotonic), or None before any look."""
        look = self._latest_look
        return None if look is None else look[1]

    def person_age(self) -> float | None:
        """Seconds since the Look detector last saw a person, or None if it never has."""
        at = self._last_person_at
        return None if at is None else self.clock() - at

    def objects(self, max_age_s: float) -> list[dict] | None:
        """The LookResult objects of the newest look if young enough, else None."""
        latest = self._latest_objects
        if latest is None or self.clock() - latest[1] > max_age_s:
            return None
        return list(latest[0])

    def look_ready(self) -> bool:
        """True once the Look model is loaded, so "no person" is an answer, not a gap."""
        ready = getattr(self.look_detector, "ready", False)
        return bool(ready() if callable(ready) else ready)

    def set_print_consent(self, authorize: Callable[[str], bool]) -> None:
        """Install the print-store authorization check for child/teen profiles."""
        self.consent_for_print = authorize

    def look_age(self) -> float | None:
        """Seconds since the newest look was taken, or None when there is none."""
        look = self._latest_look
        return None if look is None else self.clock() - look[1]

    def motion_age(self) -> float | None:
        """Seconds since something last moved in the picture, or None if nothing has."""
        at = self._last_motion_at
        return None if at is None else self.clock() - at

    def latest_look(
        self, *, max_age_s: float, take: bool = False
    ) -> tuple[bytes, int, float, Any] | None:
        """(jpeg, faces, luma, thumbnail) of the newest look if young enough; ``take`` clears it."""
        look = self._latest_look
        if look is None or self.clock() - look[1] > max_age_s:
            return None
        if take:
            self._latest_look = None
        return look[0], look[2], look[3], look[4]

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
        pose = follow_pose(target)
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
        # Imported here: it pulls the Reachy SDK, which the hub bundle does not have, and plain
        # face watching (the common case) never recognises anyone.
        from maipai_body.vision.recognize import recognize_face

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


def follow_pose(target: FaceTrackTarget) -> HeadPose:
    """Head pose that turns toward a face: yaw across the camera's field of view, pitch level plus
    up to 20 degrees for a high face. The head only travels up from level, so a face below the
    middle of the frame is level."""
    import math

    from maipai_body.bodies.stackchan.profile import (
        CENTRE_PITCH_DEG,
        FOLLOW_PITCH_SPAN_DEG,
        FOLLOW_YAW_SPAN_DEG,
    )

    assert target.x is not None and target.y is not None
    up_degrees = max(0.0, 0.5 - target.y) * FOLLOW_PITCH_SPAN_DEG
    return HeadPose(
        yaw=math.radians((target.x - 0.5) * FOLLOW_YAW_SPAN_DEG),
        pitch=math.radians(CENTRE_PITCH_DEG + up_degrees),
    )


def follow_pose_degrees(target: FaceTrackTarget) -> tuple[float, float]:
    """The same pose as `follow_pose`, as (yaw, pitch up from level) in degrees: what the person
    tracker remembers as the head's position after a follow."""
    from maipai_body.bodies.stackchan.profile import FOLLOW_PITCH_SPAN_DEG, FOLLOW_YAW_SPAN_DEG

    assert target.x is not None and target.y is not None
    return (
        (target.x - 0.5) * FOLLOW_YAW_SPAN_DEG,
        max(0.0, 0.5 - target.y) * FOLLOW_PITCH_SPAN_DEG,
    )


def _decode_jpeg(data: bytes) -> npt.NDArray[np.uint8]:
    """Decode a streamed JPEG with the bundled PyAV (the hub bundle has no OpenCV)."""
    from maipai_body.vision.jpeg import decode_jpeg

    return decode_jpeg(data)


__all__ = ["StackChanVisionBridge"]
