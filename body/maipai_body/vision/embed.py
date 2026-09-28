"""SFace's own embedding: one aligned 112x112 crop in, one 128-d
feature vector out, unnormalized (cosine similarity normalizes at
match time - `align.py`'s own docstring names the source this mirrors,
OpenCV's `FaceRecognizerSFImpl::feature()`, which builds its input
blob via `dnn::blobFromImage(aligned, 1, Size(112,112), Scalar(0,0,0),
true, false)`: no scaling (raw 0-255 float, not divided by 255), no
mean subtraction, `swapRB=true` (the aligned crop is BGR, matching the
daemon's own `get_frame()` contract - `media_manager.py`'s own
docstring - so this swaps it to the RGB order the network expects),
NCHW layout. Read line for line from OpenCV's installed source, not
assumed from a framework's usual convention, since a channel-order or
scale mistake here would not crash - it would silently degrade every
match this repo ever makes.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import numpy.typing as npt
import onnxruntime as ort

from maipai_body.model_assets import ensure_asset
from maipai_body.vision.models import SFACE

CROP_SIZE = 112
EMBEDDING_DIM = 128


def _to_blob(aligned_bgr: npt.NDArray[np.uint8]) -> npt.NDArray[np.float32]:
    if aligned_bgr.shape != (CROP_SIZE, CROP_SIZE, 3):
        raise ValueError(
            f"expected a ({CROP_SIZE}, {CROP_SIZE}, 3) aligned crop, got {aligned_bgr.shape}"
        )
    rgb = aligned_bgr[:, :, ::-1]  # BGR -> RGB, blobFromImage's own swapRB=true
    chw = rgb.transpose(2, 0, 1).astype(np.float32)  # HWC -> CHW, no /255 (scalefactor=1)
    return chw[np.newaxis, ...]  # NCHW


class SFaceEmbedder:
    """One SFace ONNX Runtime session, confined to one thread - the
    same "can't spread across cores and starve the loop" reasoning the
    vendored `FaceDetector` already applies to its own session, for
    the same reason: this runs on a capped-rate timer beside the wake
    scorer and the audio stream, never as the only thing on the CPU."""

    def __init__(self, model_path: Path) -> None:
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), options, providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name
        self._output_name = self._session.get_outputs()[0].name

    def embed(self, aligned_bgr: npt.NDArray[np.uint8]) -> npt.NDArray[np.float32]:
        """A 112x112x3 BGR aligned crop (`align.align_crop`'s own
        output) to a (128,) float32 embedding, unnormalized."""
        blob = _to_blob(aligned_bgr)
        (features,) = self._session.run([self._output_name], {self._input_name: blob})
        return features[0].astype(np.float32)


_cache_lock = threading.Lock()
_cached_embedder: SFaceEmbedder | None = None


def ensure_embedder(cache_dir: Path) -> SFaceEmbedder:
    """Downloads and verifies the SFace model if needed, then returns
    one process-wide session - loading the ONNX graph is real work
    (the design doc's own sanity check: single digits of ms per
    inference, but graph load is a separate, one-time cost), not
    something the capped-rate capture loop should repeat."""
    global _cached_embedder
    with _cache_lock:
        if _cached_embedder is None:
            model_path = ensure_asset(SFACE, cache_dir)
            _cached_embedder = SFaceEmbedder(model_path)
        return _cached_embedder
