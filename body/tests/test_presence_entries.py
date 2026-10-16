"""OFFER-01 / MOVE-CARRY-01c: presence entries by age band from the vision watch."""

from __future__ import annotations

from maipai_body.presence.entries import presence_entries_from
from maipai_body.vision.gallery import FaceVerdict
from maipai_body.vision.watch import WatchSnapshot


def _snap(present, person=None, level="identify"):
    verdict = (
        None
        if person is None and present == 0
        else FaceVerdict(person_id=person, level="confirmed" if person else "unknown", score=0.9)
    )
    return WatchSnapshot(level, present, verdict)


BANDS = {"p_adult": "adult", "p_teen": "teen", "p_kid": "child"}.get


def kinds(snapshot):
    return [e.kind for e in presence_entries_from(snapshot, BANDS) or ()]


def test_nobody_is_an_empty_list():
    assert kinds(_snap(0)) == []


def test_a_known_face_takes_its_band():
    assert kinds(_snap(1, "p_adult")) == ["adult"]
    assert kinds(_snap(1, "p_teen")) == ["teen"]
    assert kinds(_snap(1, "p_kid")) == ["child"]


def test_an_unrecognised_or_band_less_face_is_unknown():
    assert kinds(_snap(1)) == ["unknown"]
    assert kinds(_snap(1, "p_stranger")) == ["unknown"]


def test_other_faces_are_unknown_never_assumed_adult():
    assert kinds(_snap(3, "p_adult")) == ["adult", "unknown", "unknown"]


def test_a_watch_that_is_off_says_nothing():
    assert presence_entries_from(WatchSnapshot("off", 0, None), BANDS) is None
