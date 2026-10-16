"""FACE-WATCH-01: always-on recognition under watch levels.

A vision thread reads the local frame, shrinks it to 320x240, runs
YuNet at 5 Hz (2 Hz at 70 C), follows faces with a continuity rule,
embeds a new track at once and each tracked face every 2 s, and matches
against the gallery. It publishes how many faces are present and one
verdict. This replaces FACE-01's trigger from the daemon's tracker
(`run_loop._maybe_check_face`); the pipeline itself (`detect`, `align`,
`embed`, `gallery`) is reused unchanged.

Rules (OWNER-ANSWERS 4: enrolled only, a child needs a parent's
enrolment, a teen must agree, visitors are never recognised):

* The level is the stricter of the device's `robot.camera.watch_level`
  and the matched person's own `person.vision.watch`. `off` never reads
  the camera. `presence` counts faces and never embeds.
* A name is only ever produced from a synced print, and a print is only
  synced for a person who consented (hub side, FACE-CONSENT-02). A
  guest or unenrolled face matches nothing and stays `unknown`.
* The embedding of any face is a local variable of one cycle. No track,
  gallery or log keeps one, and nothing is compared across appearances,
  so nothing is inferred from repeated visits.
* The effective answer is recomputed on every read from the live level
  and the live gallery: lowering a level or revoking a print takes
  effect on the next read, not after the next embedding.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np
import numpy.typing as npt

from maipai_body.vision.align import align_crop
from maipai_body.vision.detect import FiveLandmarks
from maipai_body.vision.gallery import FaceGallery, FaceVerdict

logger = logging.getLogger("maipai_body.vision.watch")

WatchLevel = Literal["off", "presence", "identify"]
_ORDER: dict[str, int] = {"off": 0, "presence": 1, "identify": 2}

FRAME_SIZE = (320, 240)  # (width, height) the detector sees
RATE_HZ = 5.0
HOT_RATE_HZ = 2.0
HOT_AT_C = 70.0
EMBED_INTERVAL_S = 2.0
TRACK_LOSS_GRACE_S = 1.0
VERDICT_STALE_AFTER_S = 10.0
_MATCH_DISTANCE = 0.75  # a face moved less than this many face-widths is the same track

_UNKNOWN = FaceVerdict(person_id=None, level="unknown", score=0.0)


def stricter(a: WatchLevel, b: WatchLevel) -> WatchLevel:
    return a if _ORDER[a] <= _ORDER[b] else b


def read_cpu_temp_c(path: Path = Path("/sys/class/thermal/thermal_zone0/temp")) -> float | None:
    """The SoC temperature, or `None` where it cannot be read (not a Pi)."""
    try:
        return int(path.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


class _Camera(Protocol):
    def get_frame(self) -> object | None: ...


class _Detector(Protocol):
    def detect(self, frame_bgr: npt.NDArray[np.uint8]) -> list[FiveLandmarks]: ...


class _Embedder(Protocol):
    def embed(self, aligned_bgr: npt.NDArray[np.uint8]) -> npt.NDArray[np.float32]: ...


@dataclass
class _Track:
    """Scalars only: no frame, crop or embedding is ever stored here."""

    cx: float
    cy: float
    size: float
    first_seen: float
    last_seen: float
    last_embedded: float | None = None
    raw: FaceVerdict | None = None
    raw_at: float | None = None


@dataclass(frozen=True)
class WatchSnapshot:
    level: WatchLevel
    present: int
    verdict: FaceVerdict | None


class VisionWatch:
    def __init__(
        self,
        camera: _Camera,
        detector: _Detector,
        embedder: _Embedder,
        gallery: FaceGallery,
        *,
        device_level: WatchLevel = "identify",
        release_media: Callable[[], None] | None = None,
        temperature: Callable[[], float | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        verdict_stale_after_s: float = VERDICT_STALE_AFTER_S,
    ) -> None:
        self._camera = camera
        self._detector = detector
        self._embedder = embedder
        self._gallery = gallery
        self._level: WatchLevel = device_level
        self._release_media = release_media
        self._temperature = temperature
        self._clock = clock
        self._stale_after = verdict_stale_after_s
        self._tracks: list[_Track] = []
        self._released = False
        self._lock = threading.Lock()

    # -- level -------------------------------------------------------

    @property
    def device_level(self) -> WatchLevel:
        with self._lock:
            return self._level

    def set_device_level(self, level: WatchLevel) -> None:
        with self._lock:
            self._level = level
            if level == "off":
                self._tracks = []
            elif level == "presence":
                for track in self._tracks:
                    track.raw = None
                    track.raw_at = None

    def interval_s(self) -> float:
        temp = self._temperature() if self._temperature is not None else None
        hot = temp is not None and temp >= HOT_AT_C
        return 1.0 / (HOT_RATE_HZ if hot else RATE_HZ)

    # -- one cycle ---------------------------------------------------

    def step(self) -> None:
        level = self.device_level
        if level == "off":
            self._release_once()
            return
        self._released = False
        try:
            frame = self._camera.get_frame()
        except Exception:
            logger.warning("camera read failed for the vision watch", exc_info=True)
            return
        if frame is None:
            return
        try:
            self._cycle(np.asarray(frame), level)
        except Exception:
            logger.warning("vision watch cycle failed", exc_info=True)

    def _release_once(self) -> None:
        if self._released:
            return
        self._released = True
        if self._release_media is not None:
            try:
                self._release_media()
            except Exception:
                logger.warning("media release at watch level off failed", exc_info=True)

    def _cycle(self, frame: npt.NDArray[np.uint8], level: WatchLevel) -> None:
        now = self._clock()
        height, width = frame.shape[:2]
        small = _resize(frame, FRAME_SIZE)
        sx, sy = width / FRAME_SIZE[0], height / FRAME_SIZE[1]
        faces = self._detector.detect(small)
        matched = self._update_tracks(faces, now)
        if level != "identify":
            return
        for face, track in matched:
            due = track.last_embedded is None or now - track.last_embedded >= EMBED_INTERVAL_S
            if not due:
                continue
            points = face.as_points() * np.array([sx, sy])
            try:
                aligned = align_crop(frame, points)
                embedding = self._embedder.embed(aligned)
                verdict = self._gallery.identify(embedding)
            except Exception:
                logger.warning("face embedding failed", exc_info=True)
                continue
            # `aligned` and `embedding` end here: nothing below keeps them.
            track.last_embedded = now
            track.raw = verdict
            track.raw_at = now

    def _update_tracks(
        self, faces: list[FiveLandmarks], now: float
    ) -> list[tuple[FiveLandmarks, _Track]]:
        with self._lock:
            live = [t for t in self._tracks if now - t.last_seen <= TRACK_LOSS_GRACE_S]
            free = list(live)
            matched: list[tuple[FiveLandmarks, _Track]] = []
            for face in sorted(faces, key=lambda f: -f.bbox[2] * f.bbox[3]):
                x, y, w, h = face.bbox
                cx, cy, size = x + w / 2, y + h / 2, max(w, h)
                best, best_d = None, None
                for track in free:
                    d = ((track.cx - cx) ** 2 + (track.cy - cy) ** 2) ** 0.5
                    near = d <= _MATCH_DISTANCE * max(size, track.size)
                    if near and (best_d is None or d < best_d):
                        best, best_d = track, d
                if best is None:
                    best = _Track(cx, cy, size, first_seen=now, last_seen=now)
                    live.append(best)
                else:
                    free.remove(best)
                    best.cx, best.cy, best.size, best.last_seen = cx, cy, size, now
                matched.append((face, best))
            self._tracks = live
            return matched

    # -- reading -----------------------------------------------------

    def current(self) -> WatchSnapshot:
        """The effective answer now: present count plus the verdict of
        the largest (nearest) face, recomputed from the live level and
        live gallery."""
        now = self._clock()
        with self._lock:
            level = self._level
            if level == "off":
                return WatchSnapshot("off", 0, None)
            live = [t for t in self._tracks if now - t.last_seen <= TRACK_LOSS_GRACE_S]
            if not live:
                return WatchSnapshot(level, 0, None)
            nearest = max(live, key=lambda t: t.size)
            raw = nearest.raw
            fresh = nearest.raw_at is not None and now - nearest.raw_at <= self._stale_after
        if level == "presence":
            return WatchSnapshot(level, len(live), _UNKNOWN)
        if raw is None or not fresh:
            return WatchSnapshot(level, len(live), None)
        return WatchSnapshot(level, len(live), self._effective(raw, level))

    def _effective(self, raw: FaceVerdict, level: WatchLevel) -> FaceVerdict:
        """Apply the person's own level and the live gallery to a raw match."""
        if raw.person_id is not None:
            person_level = self._gallery.person_watch(raw.person_id)
            if person_level is None or stricter(level, person_level) != "identify":
                return _UNKNOWN
            return raw
        if raw.candidates:
            for candidate in raw.candidates:
                person_level = self._gallery.person_watch(candidate)
                if person_level is None or stricter(level, person_level) != "identify":
                    return FaceVerdict(person_id=None, level="unknown", score=raw.score)
        return raw

    # -- thread ------------------------------------------------------

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            started = self._clock()
            self.step()
            remaining = self.interval_s() - (self._clock() - started)
            if stop_event.wait(max(remaining, 0.0)):
                return


def _resize(frame: npt.NDArray[Any], size: tuple[int, int]) -> npt.NDArray[Any]:
    """Nearest-neighbour shrink with numpy (no image dependency here)."""
    width, height = size
    if frame.shape[1] == width and frame.shape[0] == height:
        return frame
    rows = (np.arange(height) * frame.shape[0] / height).astype(np.intp)
    cols = (np.arange(width) * frame.shape[1] / width).astype(np.intp)
    return frame[rows][:, cols]
