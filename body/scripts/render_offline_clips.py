"""G4b: render the offline speech clips from the hub's Pocket TTS.

Run on the owner's machine (not the robot, not the cloud sandbox), from
body/, against a reachable hub with a signed-in session::

    uv run python scripts/render_offline_clips.py render \
        --hub https://HUB:PORT --session-cookie VALUE --out build/clips

Writes the WAVs and a stamped ``manifest.json`` into ``--out`` and packs
``offline-clips-v1.zip`` beside them; prints the zip's sha256 to pin in
``offline_clips.BUNDLE_ASSET``. Copy the stamped manifest over
``maipai_body/speech/offline_clips.json`` and commit it. Then verify::

    uv run python scripts/render_offline_clips.py verify --out build/clips

Listen to every clip before attaching the zip to a Bot release. Record
the voice's licence check in docs/dev.md first and only then set
``voice.licence_checked`` in the manifest. Fill ``voice.name`` with the
voice actually used.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import requests

from maipai_body.model_assets import _sha256_of
from maipai_body.speech import clip_render, offline_clips


def _synthesizer(hub: str, cookie: str):
    def synthesize(text: str) -> bytes:
        response = requests.post(
            f"{hub}/api/tts",
            json={"text": text},
            headers={"Cookie": f"session={cookie}"},
            timeout=(10, 120),
        )
        response.raise_for_status()
        return response.content

    return synthesize


def _default_voice(hub: str, cookie: str) -> str:
    response = requests.get(
        f"{hub}/stack/v1/voices",
        headers={"Cookie": f"session={cookie}"},
        timeout=(10, 30),
    )
    response.raise_for_status()
    payload = response.json()
    voices = payload.get("voices", payload) if isinstance(payload, dict) else payload
    for voice in voices:
        if voice.get("default") is True:
            return str(voice.get("id") or voice.get("name"))
    raise ValueError("/stack/v1/voices did not return a default voice")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["render", "verify"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--hub")
    parser.add_argument("--session-cookie")
    args = parser.parse_args(argv)

    if args.command == "render":
        if not args.hub or not args.session_cookie:
            parser.error("render needs --hub and --session-cookie")
        voice_id = _default_voice(args.hub, args.session_cookie)
        manifest = offline_clips.load_manifest()
        manifest = replace(
            manifest,
            voice=offline_clips.Voice(
                engine="pocket-tts-english",
                name=voice_id,
                licence="CC-BY-4.0",
                credit=(
                    f"Voice {voice_id} generated with pocket-tts-english, licensed under CC-BY-4.0."
                ),
                licence_checked=False,
            ),
        )
        stamped = clip_render.render_all(
            manifest, args.out, _synthesizer(args.hub, args.session_cookie)
        )
        clip_render.write_manifest(stamped, args.out / "manifest.json")
        zip_path = clip_render.pack_bundle(stamped, args.out, args.out / "offline-clips-v1.zip")
        print(f"rendered {len(stamped.clips)} clips; bundle sha256 {_sha256_of(zip_path)}")
        return 0

    manifest = offline_clips.load_manifest(args.out / "manifest.json")
    try:
        offline_clips.ClipBundle(args.out, manifest).verify()
    except offline_clips.ClipsUnavailable as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"ok: {len(manifest.clips)} clips verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
