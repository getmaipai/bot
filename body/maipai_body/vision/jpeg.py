"""JPEG decoding for the camera frames the unit streams, with the bundled PyAV (no OpenCV)."""

from __future__ import annotations

import av
import numpy as np
import numpy.typing as npt


def decode_jpeg(data: bytes) -> npt.NDArray[np.uint8]:
    """A JPEG as a BGR uint8 array (height, width, 3), the order the YuNet detector expects."""
    if not data:
        raise ValueError("StackChan camera frame is empty; capture another frame")
    codec = av.CodecContext.create("mjpeg", "r")
    try:
        frames = codec.decode(av.Packet(data))
    except av.error.FFmpegError as exc:
        raise ValueError(
            "StackChan camera frame is not a decodable JPEG; capture another frame"
        ) from exc
    if not frames:
        raise ValueError("StackChan camera frame is not a decodable JPEG; capture another frame")
    return frames[0].to_ndarray(format="bgr24")
