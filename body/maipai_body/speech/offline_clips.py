"""G4b: pre-rendered offline speech clips - the lines the robot can say
with no hub to synthesize them.

A fixed bundle (the 32 pairing-code characters, a code prompt, the
hub-unreachable line, the freefall line, the reconnect line) rendered
once at release time and shipped as a Bot release asset, never a
tracked file. The manifest (``offline_clips.json``) is tracked: clip ids,
the text each clip speaks, file names and sha256 checksums. Checksums
are empty until the clips are rendered (``scripts/render_offline_clips.py``
stamps them); an unrendered manifest refuses to play, never silently
speaks nothing.

Playback goes through G1's :class:`AudioPlayback`, the same path G7's
streamed TTS uses, resampled to the daemon's output rate with the same
helper.
"""

from __future__ import annotations

import json
import logging
import threading
import wave
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import numpy as np
import numpy.typing as npt

from maipai_body.model_assets import AssetUnavailable as AssetUnavailable
from maipai_body.model_assets import PinnedAsset, _sha256_of, ensure_asset
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.tts_playback import _pcm16_to_float32, _resample

logger = logging.getLogger("maipai_body.speech.offline_clips")

MANIFEST_PATH = Path(__file__).parent / "offline_clips.json"

# The hub's quick-connect alphabet: 24 letters (no I, no O) and the digits
# 2 to 9 (no 0, no 1). Taken from docs/dev/reachy-mini-gap-audit-2026-09-27.md
# ("no 0/O/1/I"); `home`'s lib/quickConnect.ts is the source of truth and is
# not readable from this repo, so a release check must compare them.
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

CODE_PROMPT = "code.prompt"
UNREACHABLE = "line.unreachable"
FREEFALL = "line.freefall"
RECONNECT = "line.reconnect"
PHRASES = (UNREACHABLE, FREEFALL, RECONNECT)


def char_clip_id(char: str) -> str:
    return f"char.{char}"


class ManifestError(ValueError):
    """The manifest file is malformed."""


class ClipsUnavailable(RuntimeError):
    """The bundle is unrendered, incomplete or corrupt."""


@dataclass(frozen=True)
class Voice:
    engine: str
    name: str
    # Flipped by hand only after the licence check docs/BACKLOG.md's G4b
    # acceptance requires is recorded in docs/dev.md.
    licence_checked: bool


@dataclass(frozen=True)
class Clip:
    id: str
    text: str
    file: str
    sha256: str  # empty until rendered


@dataclass(frozen=True)
class Manifest:
    voice: Voice
    sample_rate: int
    clips: tuple[Clip, ...]

    def clip(self, clip_id: str) -> Clip:
        for c in self.clips:
            if c.id == clip_id:
                return c
        raise KeyError(clip_id)


def load_manifest(path: Path = MANIFEST_PATH) -> Manifest:
    try:
        raw = json.loads(path.read_text())
        voice = Voice(**raw["voice"])
        clips = tuple(Clip(**c) for c in raw["clips"])
        manifest = Manifest(voice=voice, sample_rate=int(raw["sample_rate"]), clips=clips)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ManifestError(f"{path}: {exc}") from exc
    seen: set[str] = set()
    for c in manifest.clips:
        if c.id in seen:
            raise ManifestError(f"duplicate clip id {c.id!r}")
        seen.add(c.id)
        if not c.file or PurePosixPath(c.file).name != c.file or c.file.startswith("."):
            raise ManifestError(f"clip {c.id!r}: unsafe file name {c.file!r}")
    return manifest


def manifest_to_json(manifest: Manifest) -> str:
    return (
        json.dumps(
            {
                "voice": {
                    "engine": manifest.voice.engine,
                    "name": manifest.voice.name,
                    "licence_checked": manifest.voice.licence_checked,
                },
                "sample_rate": manifest.sample_rate,
                "clips": [
                    {"id": c.id, "text": c.text, "file": c.file, "sha256": c.sha256}
                    for c in manifest.clips
                ],
            },
            indent=2,
        )
        + "\n"
    )


def compose_pairing_code(code: str) -> list[str]:
    """The clip ids that speak ``code``: the prompt, then each character.

    Case, spaces and hyphens are ignored; a character the hub never
    issues is an error, since no clip exists for it.
    """
    chars = [ch for ch in code.upper() if ch not in " -"]
    if not chars:
        raise ValueError("empty pairing code")
    bad = [ch for ch in chars if ch not in PAIRING_ALPHABET]
    if bad:
        raise ValueError(f"not in the pairing alphabet: {''.join(bad)!r}")
    return [CODE_PROMPT, *(char_clip_id(ch) for ch in chars)]


class ClipBundle:
    """A directory of rendered clips checked against a stamped manifest."""

    def __init__(self, directory: Path, manifest: Manifest) -> None:
        self.directory = directory
        self.manifest = manifest

    def verify(self) -> None:
        """Raises :class:`ClipsUnavailable` naming every bad clip at once."""
        unrendered = [c.id for c in self.manifest.clips if not c.sha256]
        if unrendered:
            raise ClipsUnavailable(
                f"{len(unrendered)} clips have not been rendered (no checksum in the "
                "manifest); run scripts/render_offline_clips.py"
            )
        problems = []
        for c in self.manifest.clips:
            path = self.directory / c.file
            if not path.exists():
                problems.append(f"{c.id}: missing {c.file}")
            elif _sha256_of(path) != c.sha256:
                problems.append(f"{c.id}: checksum mismatch")
        if problems:
            raise ClipsUnavailable("; ".join(problems))

    def load(self, clip_id: str) -> tuple[npt.NDArray[np.float32], int]:
        """The clip's mono float32 samples and its own sample rate,
        checksum-verified at read time."""
        clip = self.manifest.clip(clip_id)
        path = self.directory / clip.file
        if not clip.sha256:
            raise ClipsUnavailable(f"{clip_id}: has not been rendered")
        if not path.exists() or _sha256_of(path) != clip.sha256:
            raise ClipsUnavailable(f"{clip_id}: missing or checksum mismatch")
        with wave.open(str(path), "rb") as w:
            if w.getsampwidth() != 2:
                raise ClipsUnavailable(f"{clip_id}: not 16-bit PCM")
            channels, rate = w.getnchannels(), w.getframerate()
            raw = w.readframes(w.getnframes())
        return _pcm16_to_float32(raw, channels), rate


class OfflineSpeaker:
    """Speaks bundle clips through ``playback``: each resampled to the
    output rate, a silent gap pushed between them (a pushed block of
    zeros, so pacing is deterministic and needs no sleeping)."""

    def __init__(self, bundle: ClipBundle, playback: AudioPlayback, *, gap_s: float = 0.25):
        self.bundle = bundle
        self._playback = playback
        self._gap_s = gap_s
        self._said: set[str] = set()
        self._lock = threading.Lock()

    def say(self, clip_ids: list[str], *, stop_event: threading.Event | None = None) -> bool:
        """True if every clip was pushed; False if ``stop_event`` cut it
        short. An unknown id raises ``KeyError`` before anything plays."""
        for clip_id in clip_ids:
            self.bundle.manifest.clip(clip_id)
        out_rate = self._playback.output_samplerate()
        gap = np.zeros(int(self._gap_s * out_rate), dtype=np.float32)
        for i, clip_id in enumerate(clip_ids):
            if stop_event is not None and stop_event.is_set():
                return False
            samples, rate = self.bundle.load(clip_id)
            self._playback.push(_resample(samples, rate, out_rate))
            if i < len(clip_ids) - 1 and len(gap):
                self._playback.push(gap)
        return True

    def say_phrase(self, clip_id: str, *, stop_event: threading.Event | None = None) -> bool:
        return self.say([clip_id], stop_event=stop_event)

    def say_pairing_code(self, code: str, *, stop_event: threading.Event | None = None) -> bool:
        return self.say(compose_pairing_code(code), stop_event=stop_event)

    def say_phrase_once(self, clip_id: str, *, stop_event: threading.Event | None = None) -> bool:
        """Speaks the line unless already said since the last
        :meth:`rearm` ("one line once", never repeated apologies)."""
        with self._lock:
            if clip_id in self._said:
                return False
            self._said.add(clip_id)
        return self.say_phrase(clip_id, stop_event=stop_event)

    def rearm(self, clip_id: str) -> None:
        with self._lock:
            self._said.discard(clip_id)


BUNDLE_ASSET = PinnedAsset(
    file="offline-clips-v1.zip",
    url="",  # pinned once the bundle is attached to a Bot release
    sha256="",
    unavailable_hint=(
        "The offline speech clips ship as a Bot release asset rendered from "
        "the MaiPai voice; render and attach one with "
        "scripts/render_offline_clips.py (see docs/BACKLOG.md's G4b entry), "
        "then pin its URL and sha256 here."
    ),
)


def extract_bundle(zip_path: Path, target: Path) -> Path:
    """Unzips flat clip files into ``target``, refusing any member whose
    name is not a plain file name."""
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if PurePosixPath(name).name != name or name.startswith("."):
                raise ClipsUnavailable(f"unsafe member name in bundle: {name!r}")
        target.mkdir(parents=True, exist_ok=True)
        z.extractall(target)
    return target


def ensure_clip_bundle(cache_dir: Path, manifest: Manifest | None = None) -> ClipBundle:
    """Fetches (once), extracts and verifies the release bundle."""
    manifest = manifest or load_manifest()
    zip_path = ensure_asset(BUNDLE_ASSET, cache_dir)
    directory = extract_bundle(zip_path, cache_dir / "offline-clips")
    bundle = ClipBundle(directory, manifest)
    bundle.verify()
    return bundle
