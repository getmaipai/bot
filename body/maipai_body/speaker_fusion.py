"""SPEAK-04: face and voice fusion into one `speaker_evidence` and one `present`.

The rules are `dev.md` section 6, applied to the two derived answers the body
already has (a `VoiceIdentifier` result and a `FaceVerdict` from the vision
watch). Nothing here sees a template, a score or a face crop: the inputs are
person ids and levels, and the outputs are the strict spec shapes built by
`speaker_evidence.py`.

* `confirmed` is a voice match above the bar with no conflicting face on the
  speaking track, or a face match on the speaking track with a voice that
  agrees (even tentative). One signal alone is never `confirmed` for a face,
  and a voice alone keeps the level the voice gallery gave it.
* A voice and a face that name different people on the speaking track are
  `unknown`, never a pick of one of them.
* The speaking track is only unambiguous when exactly one face is in view.
  The body has no verified bearing from the array to a face (BODY bring-up), so
  with two or more faces the face is not attached to the speaker: the voice
  stands alone, a face alone gives `unknown`, and every face still counts in
  `present`.
* A face that matches nobody (a visitor, or an enrolled person the camera could
  not match) is never a conflict. It is also never silent: it counts in
  `present` as an unknown entry, so a visitor entering means "not alone".
  This is deliberately conservative: an enrolled speaker whose own face fails
  to match is not "alone" either, and the sensitive records stay withheld.
"""

from __future__ import annotations

from collections.abc import Sequence

from maipai_body.speaker_evidence import (
    PERSON_ID_RE,
    PresentEntry,
    SpeakerEvidence,
    present_entry,
    speaker_evidence,
    unknown_evidence,
)
from maipai_body.vision.gallery import FaceVerdict


def _voice_person(voice: SpeakerEvidence | None) -> tuple[str, str] | None:
    if voice is None or voice["person"] is None or voice["level"] == "unknown":
        return None
    if voice["basis"] not in ("voice", "voice_and_face"):
        return None
    return voice["person"], voice["level"]


def _face_person(face: FaceVerdict | None) -> tuple[str, str] | None:
    """A face is usable evidence only for a matched person with a well-formed id."""
    if face is None or face.person_id is None or face.level == "unknown":
        return None
    if not PERSON_ID_RE.match(face.person_id):
        return None
    return face.person_id, face.level


def fuse(
    voice: SpeakerEvidence | None, face: FaceVerdict | None, *, faces_in_view: int
) -> SpeakerEvidence:
    """One evidence for the speaker from the voice answer and the nearest face."""
    v = _voice_person(voice)
    f = _face_person(face) if faces_in_view == 1 else None
    if v and f:
        if v[0] != f[0]:
            return unknown_evidence()  # conflicting face and voice on the track
        return speaker_evidence(v[0], "voice_and_face", "confirmed")
    if v:
        return speaker_evidence(v[0], "voice", v[1])
    if f:
        return speaker_evidence(f[0], "face", "tentative")  # one signal alone, capped
    return unknown_evidence()


def build_present(
    voice_present: Sequence[PresentEntry],
    face: FaceVerdict | None,
    *,
    faces_in_view: int,
    speaker_voice_unknown: bool = False,
) -> list[PresentEntry]:
    """Everyone with a fresh track or a fresh voice, each at their own level.

    Voice entries come from the identifier (last thirty seconds). The nearest
    face adds its person when matched; every other face adds an unknown entry.
    A person seen and heard is one entry (`voice_and_face`, `confirmed`).
    An unknown voice with no face in view is one unknown entry, so the list is
    never empty while someone is talking."""
    entries: dict[str, PresentEntry] = {}
    for entry in voice_present:
        if entry["person"] is not None:
            entries[entry["person"]] = entry
    unknown_faces = faces_in_view
    nearest = _face_person(face) if faces_in_view >= 1 else None
    if nearest is not None:
        unknown_faces -= 1
        person, level = nearest
        heard = entries.get(person)
        if heard is not None:
            entries[person] = present_entry(person, "voice_and_face", "confirmed")
        else:
            entries[person] = present_entry(person, "face", level)
    out: list[PresentEntry] = list(entries.values())
    out.extend(present_entry(None, "face", "unknown") for _ in range(max(unknown_faces, 0)))
    if speaker_voice_unknown and faces_in_view == 0:
        out.append(present_entry(None, "voice", "unknown"))
    return out
