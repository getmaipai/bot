"""Documentation-only JPEG payload generator for avatar camera stream tests."""


def jpeg_frame(payload: bytes) -> bytes:
    """Build a JPEG-shaped bounded fixture with unique opaque content."""
    return b"\xff\xd8\xff\xfe" + len(payload).to_bytes(2, "big") + payload + b"\xff\xd9"
