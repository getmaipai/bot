"""The local face gallery and its own three-way verdict.

`dev.md` section 6 ("Speaker evidence on a shared device") is the
canonical rule this reimplements, not re-derives: "a close tie between
two enrolled people is `unknown` with the two candidates carried...
because a child scoring a whisker under a parent is family, not a
stranger. A far miss against every enrolled print is `unknown` with no
candidates." The legacy `perception/enroll.py`'s `FaceGallery.identify`
(best cosine score per person, margin against the runner-up) is the
reference for the scoring shape - reimplemented fresh here, not
imported, since it predates section 6's own richer three-way rule (no
candidates on a close tie) and used ArcFace, not SFace.

**A single modality never reports `confirmed`.** Section 6: confirmed
needs a face match *with a tentative voice agreeing* - a fusion this
body cannot do alone (voice runs on the hub,
`design-face-recognition-models-2026-09-28.md` section 4). A clean
face-only match is `tentative`; an ambiguous or missed one is
`unknown`. The hub's turn engine is the one place `confirmed` gets
decided, from this body's `tentative` plus its own voice result.

**Consistency by construction** (the design doc's own section 5): a
print whose model id or sha256 doesn't match the model this gallery
runs is refused, not silently compared - two different models' vector
spaces are not the same space, and a silent cross-model comparison is
exactly the failure mode that ruled out a per-device model choice in
the first place.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

logger = logging.getLogger("maipai_body.vision.gallery")


class ForeignModelPrint(RuntimeError):
    """A reference print was made by a different model than this
    gallery matches with - the Repair the design doc names, never a
    silent comparison across two incompatible embedding spaces."""


@dataclass(frozen=True)
class FacePrint:
    """One person's reference embedding. A stand-in for the real spec
    record (`commons/spec`, not built yet - design doc section 5): the
    fields this gallery actually needs to enforce model-id consistency
    and score a match, not the full record (consent metadata,
    provenance, the HLC) the real spec print will also carry."""

    id: str
    person_id: str
    model_id: str
    model_sha256: str
    embedding: npt.NDArray[np.float32]


@dataclass(frozen=True)
class FaceVerdict:
    person_id: str | None
    level: Literal["tentative", "unknown"]
    score: float
    candidates: tuple[str, ...] = ()


def _cosine(a: npt.NDArray[np.float32], b: npt.NDArray[np.float32]) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


class FaceGallery:
    """The household's synced face prints for one model, matched
    against a fresh embedding. `threshold` and `margin` are starting
    values only (OpenCV's own SFace sample: cosine 0.363; the legacy
    `FaceGallery`'s own default, 0.36, was almost certainly the same
    number, rounded) - both are set for real by the measurement M-07's
    own rule already requires, never left at these defaults."""

    def __init__(
        self,
        model_id: str,
        model_sha256: str,
        *,
        threshold: float = 0.363,
        margin: float = 0.05,
    ) -> None:
        self._model_id = model_id
        self._model_sha256 = model_sha256
        self._threshold = threshold
        self._margin = margin
        self._prints: list[FacePrint] = []
        self._lock = threading.Lock()

    def add(self, print_: FacePrint) -> None:
        if print_.model_id != self._model_id or print_.model_sha256 != self._model_sha256:
            raise ForeignModelPrint(
                f"{print_.person_id}'s print was made by {print_.model_id} "
                f"({print_.model_sha256[:12]}...), not this gallery's "
                f"{self._model_id} ({self._model_sha256[:12]}...) - re-enroll "
                "for the current model before it can match."
            )
        with self._lock:
            self._prints.append(print_)

    def remove(self, person_id: str) -> None:
        with self._lock:
            self._prints = [p for p in self._prints if p.person_id != person_id]

    def replace_all(self, prints: Iterable[FacePrint]) -> None:
        """Replace the synced snapshot, skipping prints for other models."""
        matching: list[FacePrint] = []
        for print_ in prints:
            if print_.model_id != self._model_id or print_.model_sha256 != self._model_sha256:
                logger.warning(
                    "skipping %s's print: enrolled for a different model, "
                    "re-enroll for the current model",
                    print_.person_id,
                )
                continue
            matching.append(print_)
        with self._lock:
            self._prints = matching

    def identify(self, embedding: npt.NDArray[np.float32]) -> FaceVerdict:
        """Best cosine score per person (multiple prints per person
        collapse to their own best, so multi-angle coverage doesn't
        let one person out-vote another by sheer count), then the
        three-way call: a clear leader over the threshold and margin
        is `tentative` at that person; two leaders too close together
        is `unknown` with both carried as candidates; nobody clearing
        the threshold at all is `unknown` with none."""
        with self._lock:
            prints = tuple(self._prints)
        best_per_person: dict[str, float] = {}
        for print_ in prints:
            score = _cosine(embedding, print_.embedding)
            if score > best_per_person.get(print_.person_id, -1.0):
                best_per_person[print_.person_id] = score

        if not best_per_person:
            return FaceVerdict(person_id=None, level="unknown", score=0.0)

        ranked = sorted(best_per_person.items(), key=lambda kv: kv[1], reverse=True)
        best_name, best_score = ranked[0]
        runner_up_name, runner_up_score = ranked[1] if len(ranked) > 1 else (None, 0.0)

        if best_score < self._threshold:
            return FaceVerdict(person_id=None, level="unknown", score=round(best_score, 4))

        if runner_up_name is not None and (best_score - runner_up_score) < self._margin:
            return FaceVerdict(
                person_id=None,
                level="unknown",
                score=round(best_score, 4),
                candidates=(best_name, runner_up_name),
            )

        return FaceVerdict(person_id=best_name, level="tentative", score=round(best_score, 4))
