"""G4b: the offline clip manifest, bundle, composition and playback.

Everything here runs against tiny synthetic WAVs written to tmp_path and
the fake body client; no real voice is rendered in the cloud sandbox.
"""

from __future__ import annotations

import hashlib
import io
import json
import wave
import zipfile

import numpy as np
import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.speech import offline_clips as oc
from maipai_body.speech.playback import AudioPlayback

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _wav_bytes(n_samples: int = 800, rate: int = 24_000, value: int = 1000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.full(n_samples, value, dtype="<i2").tobytes())
    return buf.getvalue()


def _install(tmp_path, manifest: oc.Manifest, *, sizes: dict[str, int] | None = None):
    """Writes a stamped bundle directory for ``manifest``; returns (dir, stamped)."""
    clips = []
    for clip in manifest.clips:
        data = _wav_bytes((sizes or {}).get(clip.id, 800))
        (tmp_path / clip.file).write_bytes(data)
        clips.append(oc.Clip(clip.id, clip.text, clip.file, hashlib.sha256(data).hexdigest()))
    return tmp_path, oc.Manifest(
        voice=manifest.voice, sample_rate=manifest.sample_rate, clips=tuple(clips)
    )


def test_manifest_covers_the_five_phrase_classes():
    manifest = oc.load_manifest()
    ids = {c.id for c in manifest.clips}
    assert {oc.char_clip_id(ch) for ch in ALPHABET} <= ids
    assert oc.CODE_PROMPT in ids
    # G4c's manifest now carries numbered randomized variants per phrase.
    picker = oc.ClipPicker(manifest)
    for line in (oc.UNREACHABLE, oc.FREEFALL, oc.RECONNECT):
        variants = picker.variants(line)
        assert len(variants) in range(4, 7)
        assert set(variants) <= ids
    assert set(oc.CARRY_LINES) <= ids
    assert len(ids) == len(manifest.clips)


def test_pairing_alphabet_is_the_32_characters_the_hub_issues():
    assert oc.PAIRING_ALPHABET == ALPHABET
    assert len(set(oc.PAIRING_ALPHABET)) == 32


def test_shipped_manifest_has_checksum_placeholders_not_invented_hashes():
    manifest = oc.load_manifest()
    assert all(c.sha256 == "" for c in manifest.clips)
    assert not manifest.voice.licence_checked


def test_manifest_rejects_a_duplicate_clip_id(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(
        json.dumps(
            {
                "voice": {"engine": "pocket-tts", "name": "x", "licence_checked": False},
                "sample_rate": 24000,
                "clips": [
                    {"id": "a", "text": "a", "file": "a.wav", "sha256": ""},
                    {"id": "a", "text": "b", "file": "b.wav", "sha256": ""},
                ],
            }
        )
    )
    with pytest.raises(oc.ManifestError, match="duplicate"):
        oc.load_manifest(path)


def test_manifest_rejects_a_path_traversing_file_name(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(
        json.dumps(
            {
                "voice": {"engine": "pocket-tts", "name": "x", "licence_checked": False},
                "sample_rate": 24000,
                "clips": [{"id": "a", "text": "a", "file": "../a.wav", "sha256": ""}],
            }
        )
    )
    with pytest.raises(oc.ManifestError, match="file name"):
        oc.load_manifest(path)


def test_compose_pairing_code_is_prompt_then_each_character():
    assert oc.compose_pairing_code("K7 mq-2z") == [
        oc.CODE_PROMPT,
        "char.K",
        "char.7",
        "char.M",
        "char.Q",
        "char.2",
        "char.Z",
    ]


@pytest.mark.parametrize("bad", ["", "AB0CDE", "ABO123", "AB1CDE", "ABCDEI"])
def test_compose_pairing_code_rejects_characters_the_hub_never_issues(bad):
    with pytest.raises(ValueError):
        oc.compose_pairing_code(bad)


def test_bundle_verify_passes_a_correctly_stamped_directory(tmp_path):
    directory, stamped = _install(tmp_path, oc.load_manifest())
    oc.ClipBundle(directory, stamped).verify()


def test_bundle_verify_reports_every_missing_and_corrupt_clip(tmp_path):
    directory, stamped = _install(tmp_path, oc.load_manifest())
    (directory / "char_A.wav").unlink()
    (directory / "char_B.wav").write_bytes(b"tampered")
    with pytest.raises(oc.ClipsUnavailable) as err:
        oc.ClipBundle(directory, stamped).verify()
    assert "char.A" in str(err.value) and "char.B" in str(err.value)


def test_bundle_refuses_an_unstamped_manifest(tmp_path):
    directory, _ = _install(tmp_path, oc.load_manifest())
    with pytest.raises(oc.ClipsUnavailable, match="not been rendered"):
        oc.ClipBundle(directory, oc.load_manifest()).verify()


def test_bundle_load_returns_float32_samples_and_the_rate(tmp_path):
    directory, stamped = _install(tmp_path, oc.load_manifest())
    samples, rate = oc.ClipBundle(directory, stamped).load(f"{oc.UNREACHABLE}.1")
    assert rate == 24_000
    assert samples.dtype == np.float32 and len(samples) == 800
    assert samples[0] == pytest.approx(1000 / 32768)


def test_bundle_load_rechecks_the_checksum_at_read_time(tmp_path):
    directory, stamped = _install(tmp_path, oc.load_manifest())
    bundle = oc.ClipBundle(directory, stamped)
    (directory / "line_unreachable_1.wav").write_bytes(_wav_bytes(value=5))
    with pytest.raises(oc.ClipsUnavailable, match="checksum"):
        bundle.load(f"{oc.UNREACHABLE}.1")


def test_speaker_pushes_a_phrase_resampled_to_the_output_rate(tmp_path):
    directory, stamped = _install(tmp_path, oc.load_manifest())
    client = FakeReachyMiniClient()  # 16 kHz output
    speaker = oc.OfflineSpeaker(oc.ClipBundle(directory, stamped), AudioPlayback(client))

    assert speaker.say_phrase(oc.UNREACHABLE) is True

    assert len(client.pushed_audio) == 1
    assert len(client.pushed_audio[0]) == pytest.approx(800 * 16_000 / 24_000, abs=2)


def test_speaker_speaks_a_code_with_a_silent_gap_between_clips(tmp_path):
    directory, stamped = _install(tmp_path, oc.load_manifest())
    client = FakeReachyMiniClient()
    speaker = oc.OfflineSpeaker(
        oc.ClipBundle(directory, stamped), AudioPlayback(client), gap_s=0.25
    )

    speaker.say_pairing_code("K7")

    # prompt, gap, K, gap, 7: three clips and two gaps, in that order
    assert len(client.pushed_audio) == 5
    gaps = [client.pushed_audio[1], client.pushed_audio[3]]
    assert all(len(g) == 4000 and not g.any() for g in gaps)
    assert all(client.pushed_audio[i].any() for i in (0, 2, 4))


def test_speaker_stops_between_clips_when_barged_in(tmp_path):
    import threading

    directory, stamped = _install(tmp_path, oc.load_manifest())
    client = FakeReachyMiniClient()
    stop = threading.Event()
    stop.set()
    speaker = oc.OfflineSpeaker(oc.ClipBundle(directory, stamped), AudioPlayback(client))

    assert speaker.say_pairing_code("K7", stop_event=stop) is False
    assert client.pushed_audio == []


def test_speaker_says_a_line_once_until_rearmed(tmp_path):
    directory, stamped = _install(tmp_path, oc.load_manifest())
    client = FakeReachyMiniClient()
    speaker = oc.OfflineSpeaker(oc.ClipBundle(directory, stamped), AudioPlayback(client))

    assert speaker.say_phrase_once(oc.UNREACHABLE) is True
    assert speaker.say_phrase_once(oc.UNREACHABLE) is False
    assert len(client.pushed_audio) == 1

    speaker.rearm(oc.UNREACHABLE)
    assert speaker.say_phrase_once(oc.UNREACHABLE) is True
    assert len(client.pushed_audio) == 2


def test_speaker_rejects_a_clip_id_that_is_not_in_the_manifest(tmp_path):
    directory, stamped = _install(tmp_path, oc.load_manifest())
    speaker = oc.OfflineSpeaker(
        oc.ClipBundle(directory, stamped), AudioPlayback(FakeReachyMiniClient())
    )
    with pytest.raises(KeyError):
        speaker.say_phrase("line.made_up")


def test_picker_never_repeats_back_to_back_over_many_draws():
    picker = oc.ClipPicker(oc.load_manifest(), lambda: 0.0)
    draws = [picker.pick(oc.UNREACHABLE) for _ in range(500)]
    assert all(a != b for a, b in zip(draws, draws[1:]))


def test_picker_supports_one_variant_and_skips_missing_variants():
    manifest = oc.Manifest(
        voice=oc.load_manifest().voice,
        sample_rate=24000,
        clips=(oc.Clip("line.test.1", "one", "one.wav", ""),),
    )
    picker = oc.ClipPicker(manifest, lambda: 0.0)
    assert picker.pick("line.test") == "line.test.1"
    assert picker.pick("line.test") == "line.test.1"
    assert picker.pick("line.test", lambda _clip: False) is None


def test_pairing_characters_stay_fixed_and_do_not_go_through_line_picker(tmp_path):
    directory, stamped = _install(tmp_path, oc.load_manifest())
    client = FakeReachyMiniClient()
    speaker = oc.OfflineSpeaker(oc.ClipBundle(directory, stamped), AudioPlayback(client))
    assert speaker.say_pairing_code("K7") is True
    assert len(client.pushed_audio) == 5


def test_ensure_bundle_without_a_hub_asset_says_it_is_not_installed(tmp_path):
    with pytest.raises(oc.AssetUnavailable, match="hub has not installed"):
        oc.ensure_clip_bundle(tmp_path)


def test_extract_bundle_refuses_a_zip_that_escapes_the_directory(tmp_path):
    zpath = tmp_path / "bad.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("../escape.wav", b"x")
    with pytest.raises(oc.ClipsUnavailable, match="unsafe"):
        oc.extract_bundle(zpath, tmp_path / "out")
