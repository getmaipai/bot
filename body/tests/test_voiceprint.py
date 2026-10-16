"""SPEAK-01: voice evidence in the body. Fake embedders only; no real model."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import numpy as np
import pytest

from maipai_body.speaker_evidence import SpeakerEvidenceError, speaker_evidence
from maipai_body.speech.voiceprint import (
    Consent,
    ConsentRequired,
    ForeignModelPrint,
    VoiceGallery,
    VoiceIdentifier,
    VoiceStore,
)

NOVA = "person-nova001"
ASTRO = "person-astro01"
MODEL = ("campp-fake", "a" * 64)


def vec(*xs: float) -> np.ndarray:
    return np.array(xs, dtype=np.float32)


def consent(person: str = NOVA) -> Consent:
    return Consent(person_id=person, consented_by=person, consent_at="2026-10-16T10:00:00Z")


def gallery(**kw) -> VoiceGallery:
    return VoiceGallery(*MODEL, **kw)


def test_evidence_shape_is_the_spec_shape() -> None:
    assert speaker_evidence(NOVA, "voice", "confirmed") == {
        "person": NOVA,
        "basis": "voice",
        "level": "confirmed",
    }
    assert speaker_evidence(None, "unknown", "unknown")["person"] is None
    with pytest.raises(SpeakerEvidenceError):
        speaker_evidence("Sage", "voice", "confirmed")
    with pytest.raises(SpeakerEvidenceError):
        speaker_evidence(NOVA, "guess", "confirmed")
    with pytest.raises(SpeakerEvidenceError):
        speaker_evidence(NOVA, "voice", "sure")


def test_three_way_known_unknown_with_candidates_and_far_miss() -> None:
    g = gallery()
    g.enroll(NOVA, [vec(1, 0, 0)], consent())
    g.enroll(ASTRO, [vec(0, 1, 0)], consent(ASTRO))
    known = g.identify(vec(1, 0.05, 0))
    assert (known.person_id, known.level) == (NOVA, "confirmed")
    tie = g.identify(vec(1, 1, 0))
    assert tie.person_id is None and tie.level == "unknown"
    assert set(tie.candidates) == {NOVA, ASTRO}
    miss = g.identify(vec(0, 0, 1))
    assert miss.person_id is None and miss.candidates == ()


def test_between_the_bars_is_tentative_and_empty_gallery_is_unknown() -> None:
    g = gallery(confirm=0.9, threshold=0.5)
    assert g.identify(vec(1, 0, 0)).level == "unknown"
    g.enroll(NOVA, [vec(1, 0, 0)], consent())
    verdict = g.identify(vec(0.7, 0.7, 0.1))
    assert (verdict.person_id, verdict.level) == (NOVA, "tentative")


def test_enrollment_needs_consent_for_that_person_and_never_a_guest() -> None:
    g = gallery()
    with pytest.raises(ConsentRequired):
        g.enroll(NOVA, [vec(1, 0, 0)], None)
    with pytest.raises(ConsentRequired):
        g.enroll(NOVA, [vec(1, 0, 0)], consent(ASTRO))
    with pytest.raises(ConsentRequired):
        g.enroll("guest", [vec(1, 0, 0)], consent("guest"))
    assert g.people() == ()


def test_foreign_model_print_is_refused() -> None:
    g = gallery()
    with pytest.raises(ForeignModelPrint):
        g.enroll(NOVA, [vec(1, 0, 0)], consent(), model=("other", "b" * 64))


def test_delete_with_the_person_removes_prints_and_file_content(tmp_path: Path) -> None:
    store = VoiceStore(tmp_path / "voice.json", *MODEL)
    g = gallery(store=store)
    g.enroll(NOVA, [vec(1, 0, 0)], consent())
    g.enroll(ASTRO, [vec(0, 1, 0)], consent(ASTRO))
    g.delete_person(NOVA)
    assert g.people() == (ASTRO,)
    assert NOVA not in (tmp_path / "voice.json").read_text()
    reloaded = gallery(store=store)
    assert reloaded.people() == (ASTRO,)


def test_store_is_private_and_survives_reload(tmp_path: Path) -> None:
    store = VoiceStore(tmp_path / "d" / "voice.json", *MODEL)
    g = gallery(store=store)
    g.enroll(NOVA, [vec(1, 0, 0)], consent())
    mode = stat.S_IMODE(os.stat(store.path).st_mode)
    assert mode == 0o600
    assert gallery(store=store).identify(vec(1, 0, 0)).person_id == NOVA


def test_store_with_a_different_model_loads_nothing(tmp_path: Path) -> None:
    store = VoiceStore(tmp_path / "voice.json", *MODEL)
    gallery(store=store).enroll(NOVA, [vec(1, 0, 0)], consent())
    other = VoiceStore(tmp_path / "voice.json", "other", "b" * 64)
    assert VoiceGallery("other", "b" * 64, store=other).people() == ()


class FakeEmbedder:
    model_id, model_sha256 = MODEL

    def __init__(self, result) -> None:
        self.result = result
        self.calls = 0

    def embed(self, samples, sample_rate):
        self.calls += 1
        return self.result


def test_identifier_needs_two_seconds_of_speech() -> None:
    g = gallery()
    g.enroll(NOVA, [vec(1, 0, 0)], consent())
    emb = FakeEmbedder(vec(1, 0, 0))
    ident = VoiceIdentifier(g, emb)
    pcm = np.zeros(16000 * 3, np.float32)
    short = ident.evidence(pcm, speech_s=1.2, doa=0.5)
    assert short == speaker_evidence(None, "unknown", "unknown") and emb.calls == 0
    long = ident.evidence(pcm, speech_s=2.4, doa=0.5)
    assert long == speaker_evidence(NOVA, "voice", "confirmed")


def test_identifier_ties_the_voice_to_a_track_by_direction_and_lists_present() -> None:
    g = gallery()
    g.enroll(NOVA, [vec(1, 0, 0)], consent())
    ident = VoiceIdentifier(g, FakeEmbedder(vec(1, 0, 0)))
    ident.evidence(np.zeros(16000 * 3, np.float32), speech_s=2.5, doa=0.4, now=100.0)
    assert ident.track_for_doa(0.45, now=101.0) == NOVA
    assert ident.track_for_doa(2.0, now=101.0) is None  # direction never identifies on its own
    assert [p["person"] for p in ident.present(now=110.0)] == [NOVA]
    assert ident.present(now=140.0) == []  # older than thirty seconds


def test_identifier_without_embedder_or_failure_is_unknown() -> None:
    g = gallery()
    assert VoiceIdentifier(g, None).evidence(np.zeros(48000, np.float32), speech_s=3.0) == (
        speaker_evidence(None, "unknown", "unknown")
    )

    class Boom(FakeEmbedder):
        def embed(self, samples, sample_rate):
            raise RuntimeError("model gone")

    out = VoiceIdentifier(g, Boom(None)).evidence(np.zeros(48000, np.float32), speech_s=3.0)
    assert out["level"] == "unknown"


def test_signed_in_is_screen_only_and_needs_a_live_touch_session() -> None:
    g = gallery()
    ident = VoiceIdentifier(g, None)
    assert ident.signed_in_evidence(NOVA, touch_live=True) == speaker_evidence(
        NOVA, "signed_in", "confirmed"
    )
    assert ident.signed_in_evidence(NOVA, touch_live=False)["basis"] == "unknown"


def test_templates_never_reach_a_payload_the_grep_test() -> None:
    root = Path(__file__).resolve().parents[1] / "maipai_body"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name in {"voiceprint.py"} or path.parts[-2] == "tests":
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"speech\.voiceprint|from \.voiceprint|VoiceStore|VoiceGallery", text):
            offenders.append(str(path.relative_to(root)))
    # Only the speech process wiring and the evidence helpers may know the gallery.
    assert not [o for o in offenders if o.startswith(("link/", "bodies/"))], offenders
    evidence = speaker_evidence(NOVA, "voice", "confirmed")
    assert set(evidence) == {"person", "basis", "level"}
