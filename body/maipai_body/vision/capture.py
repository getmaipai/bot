"""One consented frame, wrapped for the wire.

The still-image design note's own section 3: "the robot's own job is
exactly one thing: capture one frame, encode it, send it." The vendor
SDK already JPEG-encodes on the daemon's own side
(`media_manager.py`'s `get_frame_jpeg()`) - nothing here re-encodes a
raw frame, so this module needs no image-processing dependency of its
own. The wire shape (`data:image/jpeg;base64,...`) matches `home`'s
own `document_attachments` field exactly (`turn.ts:697-733`'s own
validation regex), reusing a shape a hub route can already accept
rather than inventing a new one.
"""

from __future__ import annotations

import base64

from maipai_body.hal.seam import Camera


class CameraUnavailable(RuntimeError):
    """The camera returned no frame. Distinct from `BodyLost` (a
    connection failure, raised by the client itself): this is the
    ordinary "nothing to capture right now" case - the daemon's media
    path isn't up, or the camera hardware isn't present."""


def capture_frame_data_uri(client: Camera) -> str:
    """Capture exactly one JPEG frame and wrap it as a `data:image/jpeg;
    base64,...` URI. Raises :class:`CameraUnavailable` rather than
    returning `None`: a caller reaches this only after a person's own
    explicit request (the consent event, design note section 2), so a
    missing frame is a real failure to report, not a quiet no-op."""
    frame = client.get_frame_jpeg()
    if frame is None:
        raise CameraUnavailable("the camera returned no frame")
    return f"data:image/jpeg;base64,{base64.b64encode(frame).decode('ascii')}"
