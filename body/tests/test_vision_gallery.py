"""FaceGallery's own three-way verdict, per dev.md section 6: a clear
match, a close tie carrying both candidates, and a far miss carrying
none - never `confirmed` from a single modality (that needs the hub's
own voice fusion, not this body alone)."""

from __future__ import annotations

import numpy as np
import pytest

from maipai_body.vision.gallery import FaceGallery, FacePrint, ForeignModelPrint

MODEL_ID = "sface-2021dec"
MODEL_SHA = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"


def _vec(*values: float) -> np.ndarray:
    return np.array(values, dtype=np.float32)


def _gallery(**kwargs) -> FaceGallery:
    return FaceGallery(MODEL_ID, MODEL_SHA, **kwargs)


def _print(person_id: str, embedding: np.ndarray) -> FacePrint:
    return FacePrint(
        person_id=person_id, model_id=MODEL_ID, model_sha256=MODEL_SHA, embedding=embedding
    )


def test_an_empty_gallery_is_unknown_with_no_candidates():
    gallery = _gallery()

    verdict = gallery.identify(_vec(1.0, 0.0, 0.0))

    assert verdict.person_id is None
    assert verdict.level == "unknown"
    assert verdict.candidates == ()


def test_a_clear_leader_over_threshold_and_margin_is_tentative():
    gallery = _gallery(threshold=0.5, margin=0.1)
    gallery.add(_print("sage", _vec(1.0, 0.0, 0.0)))
    gallery.add(_print("bramble", _vec(0.0, 1.0, 0.0)))

    # Near-identical to Sage's own print - a clear, confident leader.
    verdict = gallery.identify(_vec(0.99, 0.01, 0.0))

    assert verdict.person_id == "sage"
    assert verdict.level == "tentative"
    assert verdict.candidates == ()
    assert verdict.score > 0.9


def test_a_far_miss_below_threshold_is_unknown_with_no_candidates():
    gallery = _gallery(threshold=0.9, margin=0.05)
    gallery.add(_print("sage", _vec(1.0, 0.0, 0.0)))

    # Orthogonal to Sage's print - cosine similarity 0.
    verdict = gallery.identify(_vec(0.0, 1.0, 0.0))

    assert verdict.person_id is None
    assert verdict.level == "unknown"
    assert verdict.candidates == ()


def test_a_close_tie_between_two_people_is_unknown_with_both_candidates():
    """The org's own example: a child scoring a whisker under a parent
    is family, not a stranger - both names carried, not silently
    picked for the caller."""
    gallery = _gallery(threshold=0.5, margin=0.05)
    gallery.add(_print("bramble", _vec(1.0, 0.0, 0.0)))
    gallery.add(_print("bramble_child", _vec(0.999, 0.045, 0.0)))

    probe = _vec(0.9995, 0.0225, 0.0)  # almost exactly between the two
    verdict = gallery.identify(probe)

    assert verdict.person_id is None
    assert verdict.level == "unknown"
    assert set(verdict.candidates) == {"bramble", "bramble_child"}


def test_multiple_prints_per_person_use_their_own_best_not_a_sum():
    """Multi-angle coverage (several prints per person) must not let a
    person out-score another purely by having more prints stored."""
    gallery = _gallery(threshold=0.5, margin=0.05)
    # Sage has three prints, none an especially good match to the probe.
    gallery.add(_print("sage", _vec(0.1, 0.9, 0.0)))
    gallery.add(_print("sage", _vec(0.2, 0.8, 0.0)))
    gallery.add(_print("sage", _vec(0.15, 0.85, 0.0)))
    # Bramble has one print, a near-perfect match.
    gallery.add(_print("bramble", _vec(1.0, 0.0, 0.0)))

    verdict = gallery.identify(_vec(0.99, 0.01, 0.0))

    assert verdict.person_id == "bramble"


def test_adding_a_print_from_a_different_model_is_refused():
    gallery = _gallery()

    foreign = FacePrint(
        person_id="sage",
        model_id="some-other-model",
        model_sha256="f" * 64,
        embedding=_vec(1.0, 0.0, 0.0),
    )

    with pytest.raises(ForeignModelPrint):
        gallery.add(foreign)


def test_remove_drops_every_print_for_that_person():
    gallery = _gallery(threshold=0.5, margin=0.05)
    gallery.add(_print("sage", _vec(1.0, 0.0, 0.0)))
    gallery.add(_print("sage", _vec(0.9, 0.1, 0.0)))
    gallery.add(_print("bramble", _vec(0.0, 1.0, 0.0)))

    gallery.remove("sage")
    verdict = gallery.identify(_vec(0.99, 0.01, 0.0))

    assert verdict.person_id is None
    assert verdict.level == "unknown"
