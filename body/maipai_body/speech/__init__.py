"""G1: audio capture and playback through the HAL seam's ``AudioIO``.

Body-agnostic (takes any ``AudioIO``-conforming client, never a vendor
name): a capture loop that downmixes and re-chunks raw samples into fixed
32 ms mono blocks with a rolling pre-roll, and a playback writer that
opens the output stream once and keeps a ledger of what was actually
pushed. G2 (wake word) and G3 (VAD/endpointing) consume the capture side;
G7 (streamed TTS playback) consumes the playback side.
"""

from __future__ import annotations

from .capture import AudioCapture
from .playback import AudioPlayback, PushedChunk

__all__ = ["AudioCapture", "AudioPlayback", "PushedChunk"]
