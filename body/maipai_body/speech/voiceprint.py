"""SPEAK-01: voice evidence in the body.

A CAM++ embedding of an utterance with at least two seconds of speech is
matched against the voices enrolled on this robot, and the answer is one of
three (`dev.md` section 6): a known person, `unknown` with two candidates on
a close tie, or `unknown` with none (a far miss, no embedder, a short
utterance, or a failure). Direction of arrival ties a voice to a track and
never identifies anyone.

Enrollment needs a consent record for that exact person and is never silent
for a guest. Templates live only in a 0600 file beside the robot's other
private state and are deleted with the person. Nothing here updates a
template from a match: there is no such method. No module under `link/` or
`bodies/` imports this file (the grep test in `tests/test_voiceprint.py`).

The thresholds are STARTING values, UNVERIFIED: M-07 measures them on the
array. Hub-owned enrollment synced down (the 2026-09-28 amendment) reaches
the same gallery through `replace_all`; this store is the robot-only path.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import numpy.typing as npt

from maipai_body.speaker_evidence import PERSON_ID_RE, SpeakerEvidence, speaker_evidence
from maipai_body.speech.engines import SpeakerEmbedder

logger = logging.getLogger("maipai_body.speech.voiceprint")

SAMPLE_RATE = 16000
MIN_SPEECH_S = 2.0
PRESENT_WINDOW_S = 30.0
DOA_TOLERANCE_RAD = 0.35
CONFIRM_SCORE = 0.55
MATCH_SCORE = 0.35
MARGIN = 0.08


class ConsentRequired(RuntimeError):
    """Enrollment without a consent record for this person; ask on the screen first."""


class ForeignModelPrint(RuntimeError):
    """A print made by another embedding model; re-enroll for the current one."""


@dataclass(frozen=True)
class Consent:
    person_id: str
    consented_by: str
    consent_at: str


@dataclass(frozen=True)
class VoicePrint:
    person_id: str
    embedding: npt.NDArray[np.float32]
    consent_at: str
    consented_by: str


@dataclass(frozen=True)
class VoiceVerdict:
    person_id: str | None
    level: Literal["confirmed", "tentative", "unknown"]
    score: float
    candidates: tuple[str, ...] = ()


def _cosine(a: npt.NDArray[np.float32], b: npt.NDArray[np.float32]) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return 0.0 if denom == 0.0 else float(np.dot(a, b) / denom)


class VoiceStore:
    """One private file of voice templates for one embedding model."""

    def __init__(self, path: str | Path, model_id: str, model_sha256: str) -> None:
        self._path = Path(path)
        self._model = (model_id, model_sha256)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[VoicePrint]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if (data["model_id"], data["model_sha256"]) != self._model:
                logger.warning("voice templates are for another model; re-enroll")
                return []
            return [
                VoicePrint(
                    p["person_id"],
                    np.asarray(p["embedding"], dtype=np.float32),
                    p["consent_at"],
                    p["consented_by"],
                )
                for p in data["prints"]
            ]
        except FileNotFoundError:
            return []
        except Exception:
            logger.warning("voice templates unreadable; treating as none enrolled")
            return []

    def save(self, prints: Iterable[VoicePrint]) -> None:
        body = {
            "model_id": self._model[0],
            "model_sha256": self._model[1],
            "prints": [
                {
                    "person_id": p.person_id,
                    "embedding": [float(x) for x in p.embedding],
                    "consent_at": p.consent_at,
                    "consented_by": p.consented_by,
                }
                for p in prints
            ],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(body, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)


class VoiceGallery:
    def __init__(
        self,
        model_id: str,
        model_sha256: str,
        *,
        store: VoiceStore | None = None,
        confirm: float = CONFIRM_SCORE,
        threshold: float = MATCH_SCORE,
        margin: float = MARGIN,
    ) -> None:
        self._model = (model_id, model_sha256)
        self._store = store
        self._confirm = confirm
        self._threshold = threshold
        self._margin = margin
        self._lock = threading.Lock()
        self._prints: list[VoicePrint] = store.load() if store else []

    def people(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(dict.fromkeys(p.person_id for p in self._prints))

    def enroll(
        self,
        person_id: str,
        embeddings: Sequence[npt.NDArray[np.float32]],
        consent: Consent | None,
        *,
        model: tuple[str, str] | None = None,
    ) -> None:
        if (
            consent is None
            or consent.person_id != person_id
            or not consent.consented_by
            or not PERSON_ID_RE.match(person_id)
        ):
            raise ConsentRequired(
                "Voice enrollment needs the person's consent recorded on the robot's screen "
                "first. Show the consent screen for this person, then enroll."
            )
        if model is not None and model != self._model:
            raise ForeignModelPrint(
                f"{person_id}'s voice was made by {model[0]}, not {self._model[0]}; re-enroll."
            )
        new = [
            VoicePrint(
                person_id, np.asarray(e, np.float32), consent.consent_at, consent.consented_by
            )
            for e in embeddings
        ]
        with self._lock:
            self._prints.extend(new)
            self._persist()

    def delete_person(self, person_id: str) -> None:
        with self._lock:
            self._prints = [p for p in self._prints if p.person_id != person_id]
            self._persist()

    def replace_all(self, prints: Iterable[VoicePrint]) -> None:
        with self._lock:
            self._prints = list(prints)
            self._persist()

    def _persist(self) -> None:
        if self._store is not None:
            self._store.save(self._prints)

    def identify(self, embedding: npt.NDArray[np.float32]) -> VoiceVerdict:
        with self._lock:
            prints = tuple(self._prints)
        best: dict[str, float] = {}
        for p in prints:
            best[p.person_id] = max(best.get(p.person_id, -1.0), _cosine(embedding, p.embedding))
        if not best:
            return VoiceVerdict(None, "unknown", 0.0)
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        name, score = ranked[0]
        score = round(score, 4)
        if score < self._threshold:
            return VoiceVerdict(None, "unknown", score)
        if len(ranked) > 1 and score - ranked[1][1] < self._margin:
            return VoiceVerdict(None, "unknown", score, (name, ranked[1][0]))
        return VoiceVerdict(name, "confirmed" if score >= self._confirm else "tentative", score)


class VoiceIdentifier:
    """Per-utterance voice evidence, plus who was heard from which direction lately."""

    def __init__(
        self,
        gallery: VoiceGallery,
        embedder: SpeakerEmbedder | None,
        *,
        min_speech_s: float = MIN_SPEECH_S,
    ) -> None:
        self._gallery = gallery
        self._embedder = embedder
        self._min_speech_s = min_speech_s
        self._heard: dict[str, tuple[float, float | None, str]] = {}
        self.last_verdict: VoiceVerdict | None = None

    def evidence(
        self,
        pcm: npt.NDArray[np.float32],
        *,
        speech_s: float,
        doa: float | None = None,
        now: float = 0.0,
    ) -> SpeakerEvidence:
        unknown = speaker_evidence(None, "unknown", "unknown")
        if self._embedder is None or speech_s < self._min_speech_s:
            return unknown
        try:
            verdict = self._gallery.identify(self._embedder.embed(pcm, SAMPLE_RATE))
        except Exception as exc:  # noqa: BLE001 - a failed embed is unknown, never a failed turn
            logger.warning("voice embedding failed: %s", type(exc).__name__)
            return unknown
        self.last_verdict = verdict
        if verdict.person_id is None or verdict.level == "unknown":
            return unknown
        self._heard[verdict.person_id] = (now, doa, verdict.level)
        return speaker_evidence(verdict.person_id, "voice", verdict.level)

    def track_for_doa(self, doa: float, *, now: float) -> str | None:
        """The person last heard from about this direction, never an identity on its own."""
        fresh = [
            (t, person)
            for person, (t, d, _lvl) in self._heard.items()
            if d is not None and abs(d - doa) <= DOA_TOLERANCE_RAD and now - t <= PRESENT_WINDOW_S
        ]
        return max(fresh)[1] if fresh else None

    def present(self, *, now: float) -> list[SpeakerEvidence]:
        return [
            speaker_evidence(person, "voice", level)
            for person, (t, _d, level) in self._heard.items()
            if now - t <= PRESENT_WINDOW_S
        ]

    def signed_in_evidence(self, person_id: str, *, touch_live: bool) -> SpeakerEvidence:
        """The screen sign-in: authoritative only while that touch session is live."""
        if not touch_live:
            return speaker_evidence(None, "unknown", "unknown")
        return speaker_evidence(person_id, "signed_in", "confirmed")
