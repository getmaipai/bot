"""The one shape of `speaker_evidence` the body puts on a turn.

The schema (`commons/spec` conversation-turn) allows exactly
`{person, basis, level}`: a person id or null, how the body knows, and how
sure it is. Every body builds the dict here, so a template, a score or a
candidate list can never ride along by accident.
"""

from __future__ import annotations

import re
from typing import Literal, TypedDict

PERSON_ID_RE = re.compile(r"^person-[a-z0-9]{6,}$")
BASES = ("signed_in", "voice", "face", "voice_and_face", "claimed", "unknown")
LEVELS = ("confirmed", "tentative", "unknown")

Basis = Literal["signed_in", "voice", "face", "voice_and_face", "claimed", "unknown"]
Level = Literal["confirmed", "tentative", "unknown"]


class SpeakerEvidence(TypedDict):
    person: str | None
    basis: str
    level: str


class SpeakerEvidenceError(ValueError):
    """The evidence did not fit the spec shape; the message names the field."""


def speaker_evidence(person: str | None, basis: str, level: str) -> SpeakerEvidence:
    if person is not None and not PERSON_ID_RE.match(person):
        raise SpeakerEvidenceError(f"person must look like person-xxxxxx, got {person!r}")
    if basis not in BASES:
        raise SpeakerEvidenceError(f"basis must be one of {BASES}, got {basis!r}")
    if level not in LEVELS:
        raise SpeakerEvidenceError(f"level must be one of {LEVELS}, got {level!r}")
    return {"person": person, "basis": basis, "level": level}
