"""The still-image call's bot-side capture path
(`docs/dev/design-vision-still-image-2026-09-28.md`): one JPEG frame,
wrapped as a data URI in the exact shape `home`'s own
`document_attachments` field validates."""

from __future__ import annotations

import base64
import re

import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.hal.errors import BodyLost
from maipai_body.vision.capture import CameraUnavailable, capture_frame_data_uri

# home/backend/src/wire.ts's own document_attachments.data validation -
# mirrored here, not imported (a different language, a different repo),
# so this test proves this module's own output would pass that gate.
_DATA_URI_RE = re.compile(r"^data:[^;,]+;base64,[A-Za-z0-9+/]*={0,2}$")


def test_capture_wraps_real_jpeg_bytes_as_a_valid_data_uri():
    jpeg_bytes = b"\xff\xd8\xff\xe0not a real jpeg but real bytes\xff\xd9"
    client = FakeReachyMiniClient(camera_frame_jpeg=jpeg_bytes)

    data_uri = capture_frame_data_uri(client)

    assert _DATA_URI_RE.match(data_uri)
    assert data_uri.startswith("data:image/jpeg;base64,")
    encoded = data_uri.removeprefix("data:image/jpeg;base64,")
    assert base64.b64decode(encoded) == jpeg_bytes


def test_capture_raises_camera_unavailable_when_no_frame():
    client = FakeReachyMiniClient()  # no camera_frame_jpeg given

    with pytest.raises(CameraUnavailable):
        capture_frame_data_uri(client)


def test_capture_raises_body_lost_after_disconnect_not_camera_unavailable():
    client = FakeReachyMiniClient(camera_frame_jpeg=b"\xff\xd8\xff\xd9")
    client.simulate_disconnect()

    with pytest.raises(BodyLost):
        capture_frame_data_uri(client)
