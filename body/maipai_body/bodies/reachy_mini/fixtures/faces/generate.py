"""Draws the synthetic frames in this directory. Deterministic: same output every run.

``python generate.py`` rewrites ``*.npy`` here. Each frame is a flat
background with a cartoon face (skin-tone ellipse, two eyes, a mouth)
drawn from numpy primitives only: no photograph, no model, no random
seed to drift. ``no_face`` is the same background and nothing on it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

HEIGHT, WIDTH = 120, 160
BACKGROUND_BGR = (96, 84, 72)
SKIN_BGR = (150, 190, 225)
DARK_BGR = (40, 40, 60)

# name -> face centre x in pixels; None draws no face.
FRAMES: dict[str, int | None] = {
    "face_center": WIDTH // 2,
    "face_left": WIDTH // 4,
    "face_right": 3 * WIDTH // 4,
    "no_face": None,
}


def _ellipse(frame: np.ndarray, cx: float, cy: float, rx: float, ry: float, bgr) -> None:
    yy, xx = np.ogrid[: frame.shape[0], : frame.shape[1]]
    inside = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
    frame[inside] = bgr


def draw(face_x: int | None) -> np.ndarray:
    frame = np.empty((HEIGHT, WIDTH, 3), dtype=np.uint8)
    frame[:] = BACKGROUND_BGR
    if face_x is None:
        return frame
    cy = HEIGHT / 2
    _ellipse(frame, face_x, cy, 22, 28, SKIN_BGR)
    _ellipse(frame, face_x - 8, cy - 7, 3, 3, DARK_BGR)
    _ellipse(frame, face_x + 8, cy - 7, 3, 3, DARK_BGR)
    _ellipse(frame, face_x, cy + 12, 8, 2.5, DARK_BGR)
    return frame


if __name__ == "__main__":
    here = Path(__file__).parent
    for name, face_x in FRAMES.items():
        np.save(here / f"{name}.npy", draw(face_x))
