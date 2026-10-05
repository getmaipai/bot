"""G4b: play every offline clip through the real playback path on the unit.

Needs the unit (a running daemon with media) and the rendered clips.
From body/, on the robot::

    MAIPAI_BODY_UNIT=1 MAIPAI_OFFLINE_CLIPS_DIR=/path/to/clips \
        uv run python scripts/measure_offline_clips.py --host localhost --port 8000

Prints each clip's length and push time; a person listens and confirms
every clip is intelligible on the speaker (the pairing code is read back
against the app page). Nothing is measured that the daemon does not
report: no loudness or intelligibility number is invented here.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.speech import offline_clips
from maipai_body.speech.playback import AudioPlayback


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--clips-dir", type=Path, required=False)
    args = parser.parse_args()

    import os

    directory = args.clips_dir or Path(os.environ["MAIPAI_OFFLINE_CLIPS_DIR"])
    bundle = offline_clips.ClipBundle(
        directory, offline_clips.load_manifest(directory / "manifest.json")
    )
    bundle.verify()
    client = ReachyMiniClient(REACHY_MINI_PROFILE, host=args.host, port=args.port)
    try:
        playback = AudioPlayback(client)
        speaker = offline_clips.OfflineSpeaker(bundle, playback)
        for clip in bundle.manifest.clips:
            started = time.monotonic()
            speaker.say_phrase(clip.id)
            pushed = playback.pushed_duration_s()
            # Pushed audio plays in real time; wait it out before the next clip.
            time.sleep(pushed)
            push_s = time.monotonic() - started - pushed
            print(f"{clip.id:20s} {pushed:5.2f} s pushed in {push_s:.3f} s")
        playback.stop()
    finally:
        client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
