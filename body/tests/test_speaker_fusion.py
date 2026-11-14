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


# SCENE-01g: a body without a face counts. Boxes are x, y, w, h shares of the frame.
TORSO = (0.30, 0.30, 0.30, 0.60)
FACE_IN_TORSO = (0.40, 0.32, 0.10, 0.12)
OTHER_FACE = (0.80, 0.10, 0.08, 0.10)
BODY_ONLY = {"person": None, "basis": "unknown", "level": "unknown"}
FACE_ONLY = {"person": None, "basis": "face", "level": "unknown"}


def test_a_torso_with_no_face_is_one_unknown_present_entry():
    assert build_present([], None, faces_in_view=0, person_boxes=[TORSO]) == [BODY_ONLY]


def test_a_face_and_its_own_person_box_are_one_entry():
    out = build_present(
        [],
        _face(None, "unknown"),
        faces_in_view=1,
        person_boxes=[TORSO],
        face_boxes=[FACE_IN_TORSO],
    )
    assert out == [FACE_ONLY]


def test_two_torsos_with_no_faces_are_two_entries():
    other = (0.70, 0.30, 0.25, 0.60)
    out = build_present([], None, faces_in_view=0, person_boxes=[TORSO, other])
    assert out == [BODY_ONLY, BODY_ONLY]


def test_a_person_box_with_an_unrelated_face_elsewhere_yields_both():
    out = build_present(
        [], _face(None, "unknown"), faces_in_view=1, person_boxes=[TORSO], face_boxes=[OTHER_FACE]
    )
    assert out.count(FACE_ONLY) == 1
    assert out.count(BODY_ONLY) == 1


def test_an_empty_frame_yields_none():
    assert build_present([], None, faces_in_view=0, person_boxes=[], face_boxes=[]) == []


def test_a_matched_face_inside_its_box_adds_no_body_entry():
    out = build_present(
        [], _face(A), faces_in_view=1, person_boxes=[TORSO], face_boxes=[FACE_IN_TORSO]
    )
    assert out == [{"person": A, "basis": "face", "level": "confirmed"}]
