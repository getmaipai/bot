"""G1: a playback writer - opens the output stream once, keeps a ledger.

G8's own barge-in needs to know how much of a reply was actually heard
when playback is cut short mid-sentence; the ledger (what was pushed, and
when, on a monotonic clock) is what answers that without guessing from
wall-clock timing.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from maipai_body.hal.seam import AudioIO

logger = logging.getLogger("maipai_body.speech.playback")

# G7 amended by BARGE-02: listening resumes this long after the last played sample.
TAIL_S = 0.45


@dataclass
class PushedChunk:
    """One chunk actually sent to the output device, timestamped on push."""

    samples: npt.NDArray[np.float32]
    pushed_at_monotonic: float = field(default_factory=time.monotonic)


class AudioPlayback:
    """Opens ``client``'s output stream once and pushes chunks through it."""

    def __init__(self, client: AudioIO, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._client = client
        self._now = clock
        self._playing = False
        self._generation = 0
        self._cut_at: float | None = None
        self.ledger: list[PushedChunk] = []
        self._ledger_lock = threading.RLock()

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
            self._cut_at = None
            with self._ledger_lock:
                self.ledger = []

    @property
    def generation(self) -> int:
        """The reply generation playback currently accepts (BARGE-02)."""
        return self._generation

    def push(self, chunk: npt.NDArray[np.float32], generation: int | None = None) -> bool:
        """Push one chunk, opening the stream first if it isn't already.

        A chunk tagged with a generation older than the current one belongs to
        a reply that was cut; it is dropped before it reaches the device and
        ``False`` is returned. An untagged chunk is always current."""
        if generation is not None and generation != self._generation:
            return False
        self.start()
        self._client.push_audio_sample(chunk)
        with self._ledger_lock:
            self.ledger.append(PushedChunk(samples=chunk, pushed_at_monotonic=self._now()))
        return True

    def flush(self) -> None:
        """Barge-in: end the current generation, stop output and drop what the
        daemon still holds queued (the SDK's ``clear_player``), so no queued
        sample plays after the cut. The ledger keeps the heard prefix."""
        self._generation += 1
        self._cut_at = self._now()
        clear = getattr(self._client, "clear_player", None)
        if clear is not None:
            try:
                clear()
            except Exception:
                logger.warning("clearing the daemon's queued audio failed", exc_info=True)
        self.stop()

    def listen_again_at(self, tail_s: float = TAIL_S) -> float:
        """When the capture may be scored again: the end of the last played
        sample (or the cut, if the reply was flushed) plus the tail. ``0.0``
        when nothing was played."""
        rate = self.output_samplerate()
        with self._ledger_lock:
            chunks = [(c.pushed_at_monotonic, len(c.samples)) for c in self.ledger]
        if not chunks or not rate:
            return 0.0
        end = 0.0
        for pushed_at, n in chunks:
            end = max(end, pushed_at) + n / rate
        if self._cut_at is not None:
            end = min(end, self._cut_at)
        return end + tail_s

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

    def recent_rms(self, now: float | None = None, window_s: float = 0.2) -> float:
        """RMS of the actual recent output samples, for energy-modulated motion."""
        stamp = self._now() if now is None else now
        with self._ledger_lock:
            chunks = [
                chunk.samples
                for chunk in self.ledger
                if 0.0 <= stamp - chunk.pushed_at_monotonic <= window_s
            ]
        if not chunks:
            return 0.0
        total = sum(float((chunk.astype("float64") ** 2).sum()) for chunk in chunks)
        count = sum(chunk.size for chunk in chunks)
        return (total / count) ** 0.5 if count else 0.0
