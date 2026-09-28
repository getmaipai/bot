"""G1: a playback writer - opens the output stream once, keeps a ledger.

G8's own barge-in needs to know how much of a reply was actually heard
when playback is cut short mid-sentence; the ledger (what was pushed, and
when, on a monotonic clock) is what answers that without guessing from
wall-clock timing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from maipai_body.hal.seam import AudioIO


@dataclass
class PushedChunk:
    """One chunk actually sent to the output device, timestamped on push."""

    samples: npt.NDArray[np.float32]
    pushed_at_monotonic: float = field(default_factory=time.monotonic)


class AudioPlayback:
    """Opens ``client``'s output stream once and pushes chunks through it."""

    def __init__(self, client: AudioIO) -> None:
        self._client = client
        self._playing = False
        self.ledger: list[PushedChunk] = []

    def start(self) -> None:
        """Idempotent: safe to call once per reply even if already open.

        Clears the previous reply's ledger here, not in :meth:`stop`, so
        barge-in can call ``stop()`` to halt output and then read
        ``pushed_duration_s()`` for what was actually heard, without a
        race against the ledger it just asked about.
        """
        if not self._playing:
            self._client.start_playing()
            self._playing = True
            self.ledger = []

    def push(self, chunk: npt.NDArray[np.float32]) -> None:
        """Push one chunk, opening the stream first if it isn't already."""
        self.start()
        self._client.push_audio_sample(chunk)
        self.ledger.append(PushedChunk(samples=chunk))

    def stop(self) -> None:
        """Close the output stream. The ledger survives until the next
        :meth:`start`, so a caller can still read ``pushed_duration_s()``
        right after cutting playback short."""
        if self._playing:
            self._client.stop_playing()
            self._playing = False

    def pushed_duration_s(self) -> float:
        """Total seconds of audio actually pushed since the last :meth:`stop`."""
        sample_rate = self.output_samplerate()
        if not sample_rate:
            return 0.0
        total_samples = sum(len(c.samples) for c in self.ledger)
        return total_samples / sample_rate

    def output_samplerate(self) -> int:
        """The daemon's own output rate - what G7's own resampler
        targets, so a caller doesn't need to reach into this class's
        private ``_client`` to ask the seam directly."""
        return self._client.get_output_audio_samplerate()
