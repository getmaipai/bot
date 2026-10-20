"""The five alignment points of one detected face.

Kept apart from `detect.py` so code that only reads landmarks (the watch,
the StackChan hub build) never imports the Reachy SDK, which `detect.py`
needs for the YuNet detector it subclasses.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class FiveLandmarks:
    """A detected face's five alignment points, in the order SFace's
    own template expects: right eye, left eye, nose, right mouth
    corner, left mouth corner."""

    bbox: tuple[float, float, float, float]
    right_eye: tuple[float, float]
    left_eye: tuple[float, float]
    nose: tuple[float, float]
    right_mouth: tuple[float, float]
    left_mouth: tuple[float, float]

    def as_points(self) -> npt.NDArray[np.float64]:
        """The five points as a (5, 2) array - `align.similarity_transform`'s own input shape."""
        return np.array(
            [self.right_eye, self.left_eye, self.nose, self.right_mouth, self.left_mouth],
            dtype=np.float64,
        )
