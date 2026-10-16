"""SPEAK-04: fuse() and build_present() on the dev.md section 6 rules."""

from __future__ import annotations

from maipai_body.speaker_evidence import present_entry, speaker_evidence, unknown_evidence
from maipai_body.speaker_fusion import build_present, fuse
from maipai_body.vision.gallery import FaceVerdict

A, B = "person-anna01", "person-ben002"


def _face(person, level="confirmed"):
    return FaceVerdict(person_id=person, level=level, score=0.9)


def test_voice_alone_keeps_its_level():
    assert fuse(speaker_evidence(A, "voice", "tentative"), None, faces_in_view=0) == {
        "person": A,
        "basis": "voice",
        "level": "tentative",
    }


def test_face_alone_is_capped_at_tentative():
    assert fuse(None, _face(A, "confirmed"), faces_in_view=1) == {
        "person": A,
        "basis": "face",
        "level": "tentative",
    }


def test_agreement_is_confirmed_on_both():
    assert fuse(speaker_evidence(A, "voice", "tentative"), _face(A), faces_in_view=1) == {
        "person": A,
        "basis": "voice_and_face",
        "level": "confirmed",
    }


def test_disagreement_is_unknown_not_a_pick():
    assert (
        fuse(speaker_evidence(A, "voice", "confirmed"), _face(B), faces_in_view=1)
        == unknown_evidence()
    )


def test_an_unmatched_face_is_never_a_conflict():
    assert (
        fuse(speaker_evidence(A, "voice", "confirmed"), _face(None, "unknown"), faces_in_view=1)[
            "basis"
        ]
        == "voice"
    )


def test_with_two_faces_the_face_is_not_attached_to_the_speaker():
    assert fuse(None, _face(A), faces_in_view=2) == unknown_evidence()
    assert fuse(speaker_evidence(A, "voice", "confirmed"), _face(B), faces_in_view=2)["person"] == A


def test_present_counts_every_face_and_merges_a_person_seen_and_heard():
    out = build_present([present_entry(A, "voice", "tentative")], _face(A), faces_in_view=3)
    assert out.count({"person": A, "basis": "voice_and_face", "level": "confirmed"}) == 1
    assert out.count({"person": None, "basis": "face", "level": "unknown"}) == 2


def test_present_is_never_empty_while_an_unknown_voice_talks():
    assert build_present([], None, faces_in_view=0, speaker_voice_unknown=True) == [
        {"person": None, "basis": "voice", "level": "unknown"}
    ]
    assert build_present([], None, faces_in_view=0) == []
