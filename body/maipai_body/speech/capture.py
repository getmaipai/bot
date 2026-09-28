"""G1: pulls raw audio from an ``AudioIO`` client and re-chunks it.

The seam hands back whatever the underlying stream happens to have
queued on any given call - a real GStreamer appsink's buffer, a fake's
own fixed-size slice, never a guaranteed block size. Everything above
this module (the wake scorer, G2; the endpointer, G3) wants a steady
32 ms mono cadence instead, so this is the one place that downmixes and
re-chunks, and the one place that remembers the last 0.3 s so a consumer
that only starts caring once it hears a wake word still gets the syllable
that came just before it.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np
import numpy.typing as npt

from maipai_body.hal.seam import AudioIO

BLOCK_SAMPLES = 512  # 32 ms at 16 kHz - EXPR-01's own "one control tick" scale
PRE_ROLL_S = 0.3


class AudioCapture:
    """Downmixes and re-chunks ``client``'s raw audio into fixed blocks.

    Call :meth:`start` once, then :meth:`poll_blocks` as often as the
    caller likes (a tight loop, a timer tick); each call drains whatever
    is currently queued and returns zero or more *complete* 32 ms mono
    blocks, holding any leftover samples for the next call rather than
    padding or dropping them.
    """

    def __init__(self, client: AudioIO) -> None:
        self._client = client
        self._sample_rate = 0
        self._leftover: npt.NDArray[np.float32] = np.zeros(0, dtype=np.float32)
        preroll_blocks = 1  # replaced once start() knows the real sample rate
        self._preroll: deque[npt.NDArray[np.float32]] = deque(maxlen=preroll_blocks)

    def start(self) -> None:
        """Open the input stream and size the pre-roll ring to at least 0.3 s.

        Rounds up to a whole block count: a wake word's leading syllable
        must not be clipped, so the ring holds slightly more than 0.3 s
        rather than rounding to the nearest block and risking less.
        """
        self._client.start_recording()
        self._sample_rate = self._client.get_input_audio_samplerate()
        preroll_blocks = max(1, math.ceil((PRE_ROLL_S * self._sample_rate) / BLOCK_SAMPLES))
        self._preroll = deque(maxlen=preroll_blocks)
        self._leftover = np.zeros(0, dtype=np.float32)

    def stop(self) -> None:
        self._client.stop_recording()

    def poll_blocks(self) -> list[npt.NDArray[np.float32]]:
        """Drain whatever is queued right now into complete 32 ms mono blocks.

        ``get_audio_sample()`` hands back one buffer per call - a real
        GStreamer appsink's queue can hold more than one, so this calls
        it in a loop until it returns ``None`` rather than once, or a
        slow-polling caller would fall behind the daemon's own queue.

        Downmixes multi-channel input to mono by taking channel 0 - the
        gap-audit's own G1 section named this as the simpler of its two
        listed options ("channel 0, or the mean"); nothing in the vendor
        SDK or the design record documents which physical array element
        either channel actually is, so averaging would risk silently
        blending in whatever the array's second channel turns out to be,
        for no documented benefit. Returns ``[]``, never ``None``, when
        nothing new is queued.
        """
        buffer = self._leftover
        while True:
            sample = self._client.get_audio_sample()
            if sample is None:
                break
            mono = sample[:, 0] if sample.ndim == 2 else sample
            buffer = np.concatenate([buffer, mono.astype(np.float32)])
        n_blocks = len(buffer) // BLOCK_SAMPLES
        blocks: list[npt.NDArray[np.float32]] = []
        for i in range(n_blocks):
            block = buffer[i * BLOCK_SAMPLES : (i + 1) * BLOCK_SAMPLES]
            blocks.append(block)
            self._preroll.append(block)
        self._leftover = buffer[n_blocks * BLOCK_SAMPLES :]
        return blocks

    def preroll(self) -> npt.NDArray[np.float32]:
        """The last ~0.3 s of audio, oldest first - what should precede
        the first real speech block in an endpointed utterance (G3)."""
        if not self._preroll:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(list(self._preroll))
