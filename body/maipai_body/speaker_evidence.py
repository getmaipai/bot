"""The one shape of `speaker_evidence` the body puts on a turn.

The schema (`commons/spec` conversation-turn) allows exactly
`{person, basis, level}`: a person id or null, how the body knows, and how
sure it is. Every body builds the dict here, so a template, a score or a
candidate list can never ride along by accident.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
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


# SPEAK-02: what the evidence means once it is on the turn. These mirror the
# hub's reading (`home/backend/src/lib/turnContext.ts`: effectiveBand and
# sensitiveAllowed), so the robot decides locally exactly as the hub will.

AgeBand = Literal["adult", "teen", "child"]


class PresentEntry(TypedDict):
    person: str | None
    basis: str
    level: str


def unknown_evidence() -> SpeakerEvidence:
    return speaker_evidence(None, "unknown", "unknown")


def present_entry(person: str | None, basis: str, level: str) -> PresentEntry:
    """One `present` entry: the same strict shape as the speaker's evidence."""
    return speaker_evidence(person, basis, level)


def opens_ceiling(evidence: SpeakerEvidence | None) -> bool:
    """Only `confirmed` and `signed_in` open the content ceiling, `adult_only`
    disclosure, `sensitive` records, consequential actions and settings. A
    claim, a tentative match and an unknown speaker never do."""
    if evidence is None or evidence["person"] is None:
        return False
    return evidence["basis"] == "signed_in" or evidence["level"] == "confirmed"


def claimed_evidence(person: str, *, contradicted_by: Sequence[str | None] = ()) -> SpeakerEvidence:
    """The answer to the who-is-speaking ask, or "it's me, Sage".

    It selects the person for personalization and is never access: the level
    is `tentative`, which `opens_ceiling` refuses. When an enrolled print for
    another person disagrees (a voice or a face match on the speaking track),
    the claim is not believed and the turn is `unknown`."""
    if any(other is not None and other != person for other in contradicted_by):
        return unknown_evidence()
    return speaker_evidence(person, "claimed", "tentative")


def effective_band(
    evidence: SpeakerEvidence | None, band_of: Callable[[str], AgeBand | None]
) -> tuple[AgeBand, str]:
    """The age band a robot turn is held to, and its basis.

    An absent, `unknown`-level or person-less speaker is the child band
    (`unknown_speaker_default`); nothing reads the utterance for the band, and
    a claim cannot raise it (a claim whose person has no known band is also
    the child default). Tightening only."""
    if evidence is None or evidence["level"] == "unknown" or evidence["person"] is None:
        return "child", "unknown_speaker_default"
    band = band_of(evidence["person"])
    if band is None:
        return "child", "unknown_speaker_default"
    return band, "identified_profile"


def present_and_alone(
    evidence: SpeakerEvidence | None, present: Sequence[PresentEntry] | None
) -> bool:
    """Confirmed present and alone: exactly one entry in the whole list, at
    `confirmed`, and it is the speaker. A second person at any level, known,
    tentative or unknown, means not alone; a missing or empty list means the
    body said nothing, so nothing sensitive is said."""
    if not present or len(present) != 1 or evidence is None or evidence["person"] is None:
        return False
    only = present[0]
    return only["person"] == evidence["person"] and only["level"] == "confirmed"


def sensitive_allowed(
    evidence: SpeakerEvidence | None, present: Sequence[PresentEntry] | None
) -> bool:
    return opens_ceiling(evidence) and present_and_alone(evidence, present)
