"""VOICE-03: resolve a companion's voice binding to a voice installed here.

A companion's ``voice_id`` names a voice package. When that package is not
installed on this robot (or does not list the ``bot`` platform) the robot uses
its default voice and says so: ``notice`` is the text the companion's settings
row shows. It is never a silent substitution, and the companion itself is never
swapped for another one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

VOICE_UNAVAILABLE_NOTICE = "voice not available on this robot"


class NoVoiceInstalled(RuntimeError):
    """Not even the default voice is installed; speech cannot start."""


@dataclass(frozen=True)
class InstalledVoice:
    voice_id: str
    platforms: tuple[str, ...] = ("home", "bot")
    model_path: str | None = None  # the Piper model this package ships, for the TTS engine


@dataclass(frozen=True)
class VoiceChoice:
    voice: InstalledVoice
    requested_id: str | None
    notice: str | None  # None when the bound voice is the one speaking


def resolve_voice(
    requested_id: str | None,
    installed: Mapping[str, InstalledVoice],
    default_id: str,
) -> VoiceChoice:
    def usable(voice_id: str) -> InstalledVoice | None:
        voice = installed.get(voice_id)
        return voice if voice is not None and "bot" in voice.platforms else None

    if requested_id:
        bound = usable(requested_id)
        if bound is not None:
            return VoiceChoice(voice=bound, requested_id=requested_id, notice=None)
    default = usable(default_id)
    if default is None:
        raise NoVoiceInstalled(
            f"the default voice {default_id!r} is not installed on this robot; "
            "install a voice package from the catalog"
        )
    return VoiceChoice(
        voice=default,
        requested_id=requested_id,
        notice=VOICE_UNAVAILABLE_NOTICE if requested_id else None,
    )
