"""One frame in, one verdict out - `detect` -> `align` -> `embed` ->
`gallery`, the whole offline half of FACE-01. Not yet called from
anywhere: the capture cadence (opportunistic, capped-rate, triggered
by the presence system's own `get_face_target()`) and the
`speaker_evidence` wiring onto the outgoing turn are their own,
separate piece of work against `run_loop.py`, deliberately not bundled
into this same change (`dev.md` section 6's own scoring pipeline
first, proven on its own, before it touches the run loop G9 already
landed and reviewed).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from maipai_body.vision.align import align_crop
from maipai_body.vision.detect import FiveLandmarkDetector
from maipai_body.vision.embed import SFaceEmbedder
from maipai_body.vision.gallery import FaceGallery, FaceVerdict


def recognize_face(
    frame_bgr: npt.NDArray[np.uint8],
    *,
    detector: FiveLandmarkDetector,
    embedder: SFaceEmbedder,
    gallery: FaceGallery,
) -> FaceVerdict | None:
    """The first detected face's verdict, or `None` if no face is in
    the frame at all - distinct from :class:`FaceVerdict`'s own
    `level="unknown"`, which means a face was found but not matched.
    Multiple faces in one frame: only the first (YuNet's own
    detection order) is scored: the presence system this is triggered
    from already tracks one speaking track at a time (`dev.md` section
    6's own "the speaking track"), not a crowd."""
    faces = detector.detect(frame_bgr)
    if not faces:
        return None
    aligned = align_crop(frame_bgr, faces[0].as_points())
    embedding = embedder.embed(aligned)
    return gallery.identify(embedding)
