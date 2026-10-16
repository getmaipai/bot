"""VOICE-03: the shared normalizer and the voice binding row."""

from __future__ import annotations

import pytest

from maipai_body.speech.normalize import (
    NormalizerUnavailable,
    load_fixtures,
    load_normalizer,
    spec_dir,
)
from maipai_body.speech.voices import (
    VOICE_UNAVAILABLE_NOTICE,
    InstalledVoice,
    NoVoiceInstalled,
    resolve_voice,
)

INSTALLED = {
    "piper-amy": InstalledVoice("piper-amy"),
    "piper-hub-only": InstalledVoice("piper-hub-only", platforms=("home",)),
}


def test_a_bound_voice_that_is_installed_speaks_with_no_notice():
    choice = resolve_voice("piper-amy", INSTALLED, default_id="piper-amy")
    assert choice.voice.voice_id == "piper-amy" and choice.notice is None


@pytest.mark.parametrize("bound", ["piper-missing", "piper-hub-only"])
def test_a_voice_this_robot_lacks_falls_back_loudly(bound):
    choice = resolve_voice(bound, INSTALLED, default_id="piper-amy")
    assert choice.voice.voice_id == "piper-amy"
    assert choice.notice == VOICE_UNAVAILABLE_NOTICE
    assert choice.requested_id == bound  # the companion keeps its binding


def test_no_binding_uses_the_default_without_a_notice():
    choice = resolve_voice(None, INSTALLED, default_id="piper-amy")
    assert choice.voice.voice_id == "piper-amy" and choice.notice is None


def test_no_default_installed_is_an_error_that_says_what_to_do():
    with pytest.raises(NoVoiceInstalled, match="install a voice package"):
        resolve_voice("piper-amy", {}, default_id="piper-amy")


def test_a_missing_spec_dir_says_how_to_fix_it(tmp_path):
    with pytest.raises(NormalizerUnavailable, match="MAIPAI_SPEC_DIR"):
        load_normalizer(tmp_path)


def test_the_robot_normalizer_passes_the_shared_fixtures():
    pytest.importorskip("num2words")
    if not (spec_dir() / "voice" / "py" / "normalize_for_speech.py").is_file():
        pytest.skip("pinned spec source not found (set MAIPAI_SPEC_DIR)")
    normalize = load_normalizer()
    fixtures = load_fixtures()
    assert len(fixtures) >= 50
    wrong = [
        (f["input"], normalize(f["input"]))
        for f in fixtures
        if normalize(f["input"]) != f["expected"]
    ]
    assert wrong == []
