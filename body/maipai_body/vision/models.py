"""FACE-01's own model file, fetched on demand.

"Download, don't vendor": the file is a pinned URL plus a sha256
checksum, fetched into a local cache directory and verified before
use, never tracked in this repo - the same `model_assets.PinnedAsset`
mechanism G2's wake word already uses.

SFace (`docs/dev/design-face-recognition-models-2026-09-28.md`):
OpenCV Zoo's `face_recognition_sface_2021dec.onnx`, Apache-2.0, a
MobileFaceNet backbone. OpenCV Zoo stores its model files in Git LFS,
so a plain `raw.githubusercontent.com` URL only serves the LFS pointer
text, not the binary - `media.githubusercontent.com`'s own LFS media
endpoint is the one that serves the real bytes (verified today: the
raw URL's own pointer file names the same sha256 and byte count as
below, confirming the pin without needing to trust it blind; the media
URL was then downloaded and its sha256 checked directly, and its ONNX
graph read with this repo's own pinned `onnxruntime`: input `data`
`[1, 3, 112, 112]` float, output `fc1` `[1, 128]` float, exactly as
the design doc records). Pinned to a commit, not `main`, so the URL
itself can't silently start serving different bytes at the same path.
"""

from __future__ import annotations

from maipai_body.model_assets import PinnedAsset

_OPENCV_ZOO_COMMIT = "ba91a3b91d00d76e86540d4013f944bd6b514e39"
_OPENCV_ZOO_MEDIA_BASE = (
    f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{_OPENCV_ZOO_COMMIT}"
)

SFACE = PinnedAsset(
    file="face_recognition_sface_2021dec.onnx",
    url=f"{_OPENCV_ZOO_MEDIA_BASE}/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
)
