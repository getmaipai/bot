from __future__ import annotations

import time

import numpy as np
import pytest

from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.vision_bridge import StackChanVisionBridge
from maipai_body.vision.detect import FiveLandmarks
from maipai_body.vision.gallery import FaceVerdict

FACE = FiveLandmarks((90, 60, 80, 90), (110, 85), (150, 85), (130, 105), (115, 125), (145, 125))


class Detector:
    def __init__(self, faces):
        self.faces = faces

    def detect(self, frame):
        return self.faces


class Embedder:
    def embed(self, aligned):
        return np.ones(128, dtype=np.float32)


class Gallery:
    def identify(self, embedding):
        return FaceVerdict("sage", "tentative", 0.91)


def bridge(tmp_path, faces=(), gallery=None):
    client = FakeStackChanDeviceClient()
    client.photo = b"\xff\xd8synthetic-frame\xff\xd9"
    robot = StackChanRobotAdapter(client)
    return client, StackChanVisionBridge(
        robot.robot,
        detector=Detector(list(faces)),
        embedder=Embedder(),
        gallery=gallery or Gallery(),
        decode=lambda _: np.zeros((240, 320, 3), dtype=np.uint8),
        temp_dir=tmp_path,
    )


def test_tracking_uses_anonymous_clamped_robot_correction(tmp_path):
    client, vision = bridge(tmp_path, [FACE])
    target = vision.track_once()
    assert target.detected and not hasattr(target, "person_id")
    commands = [call for call in client.calls if call.name == "self.robot.set_head_angles"]
    assert commands
    assert -128 <= commands[-1].arguments["yaw"] <= 128
    assert 5 <= commands[-1].arguments["pitch"] <= 85


def test_tracking_correction_times_out_and_holds_head(tmp_path):
    client, vision = bridge(tmp_path, [FACE])
    vision.track_once(deadline_s=0.03)
    time.sleep(0.08)
    assert client.cancelled_motion_batches >= 1


def test_unknown_face_does_not_return_identity(tmp_path):
    unknown = FaceVerdict(None, "unknown", 0.2)
    _, vision = bridge(
        tmp_path, [FACE], gallery=type("G", (), {"identify": lambda self, _: unknown})()
    )
    result = vision.recognize_once()
    assert result.person_id is None
    assert result.level == "unknown"


def test_child_print_requires_explicit_consent(tmp_path):
    client, vision = bridge(tmp_path, [FACE])
    vision.set_print_consent(lambda person_id: False)
    with pytest.raises(PermissionError, match="consent"):
        vision.recognize_once(person_id="sage", age_group="child")
    assert not [call for call in client.calls if call.name == "camera.take_photo"]


def test_photo_bytes_are_not_written_and_temp_dir_is_cleaned(tmp_path):
    client, vision = bridge(tmp_path, [FACE])
    vision.recognize_once()
    assert list(tmp_path.iterdir()) == []
    assert client.photo == b"\xff\xd8synthetic-frame\xff\xd9"


def test_hub_still_requires_consent_and_forwards_only_explicitly(tmp_path):
    client, vision = bridge(tmp_path)
    sent = []
    with pytest.raises(PermissionError, match="consent"):
        vision.send_consented_hub_still(sent.append, authorize=lambda: False)
    assert sent == []
    vision.send_consented_hub_still(sent.append, authorize=lambda: True)
    assert sent == [client.photo]


def test_tracking_accepts_consecutive_frames_under_its_lease(tmp_path):
    client, vision = bridge(tmp_path, [FACE])
    vision.track_once(deadline_s=0.1)
    vision.track_once(deadline_s=0.03)
    time.sleep(0.07)
    assert client.cancelled_motion_batches >= 1
