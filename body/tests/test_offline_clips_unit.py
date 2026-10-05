"""G4b: the offline clips against real rendered audio and the real unit.

Both are skipped without their inputs and never fail the cloud suite.
Needs the unit (see scripts/measure_offline_clips.py for the command).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from maipai_body.speech import offline_clips as oc

_CLIPS_DIR = os.environ.get("MAIPAI_OFFLINE_CLIPS_DIR")

needs_rendered = pytest.mark.skipif(
    not _CLIPS_DIR, reason="MAIPAI_OFFLINE_CLIPS_DIR does not point at rendered clips"
)
needs_unit = pytest.mark.skipif(
    os.environ.get("MAIPAI_BODY_UNIT") != "1" or not _CLIPS_DIR,
    reason="hardware-only: needs MAIPAI_BODY_UNIT=1 on the unit and MAIPAI_OFFLINE_CLIPS_DIR",
)


def _bundle() -> oc.ClipBundle:
    directory = Path(_CLIPS_DIR)  # type: ignore[arg-type]
    return oc.ClipBundle(directory, oc.load_manifest(directory / "manifest.json"))


@needs_rendered
def test_rendered_bundle_verifies_and_every_clip_is_audible_and_short():
    bundle = _bundle()
    bundle.verify()
    for clip in bundle.manifest.clips:
        samples, rate = bundle.load(clip.id)
        assert 0.1 < len(samples) / rate < 8.0, clip.id
        assert float(np.abs(samples).max()) > 0.01, clip.id


@needs_unit
def test_every_clip_plays_through_the_real_playback_path():
    from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
    from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
    from maipai_body.speech.playback import AudioPlayback

    client = ReachyMiniClient(REACHY_MINI_PROFILE, host="localhost", port=8000)
    try:
        playback = AudioPlayback(client)
        speaker = oc.OfflineSpeaker(_bundle(), playback)
        for clip in speaker.bundle.manifest.clips:
            assert speaker.say_phrase(clip.id) is True
            assert playback.pushed_duration_s() > 0
        playback.stop()
    finally:
        client.disconnect()
