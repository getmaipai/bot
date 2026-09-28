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

BLOCK_DURATION_S = 0.032  # 32 ms - EXPR-01's own "one control tick" scale
BLOCK_SAMPLES = 512  # BLOCK_DURATION_S at 16 kHz, the only rate any real body reports today
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
        self._recording = False
        self._sample_rate = 0
        self._block_samples = BLOCK_SAMPLES  # sized to the real rate once start() knows it
        self._leftover: npt.NDArray[np.float32] = np.zeros(0, dtype=np.float32)
        preroll_blocks = 1  # replaced once start() knows the real sample rate
        self._preroll: deque[npt.NDArray[np.float32]] = deque(maxlen=preroll_blocks)

    def start(self) -> None:
        """Open the input stream and size the pre-roll ring to at least 0.3 s.

        Idempotent, like :meth:`AudioPlayback.start`: a second call while
        already recording would otherwise discard ``_leftover`` and the
        pre-roll ring for no reason. Sizes ``_block_samples`` from the
        stream's own reported rate rather than assuming 16 kHz - the seam's
        own contract (``hal/seam.py``) - even though every real body today
        happens to report that rate. Rounds the pre-roll ring up to a whole
        block count: a wake word's leading syllable must not be clipped, so
        the ring holds slightly more than 0.3 s rather than rounding to the
        nearest block and risking less.

        ``_recording`` flips only once sizing has actually succeeded: if
        ``get_input_audio_samplerate()`` raises, a retried ``start()`` must
        not be silently swallowed by the idempotency guard above with
        sizing left stale.
        """
        if self._recording:
            return
        self._client.start_recording()
        sample_rate = self._client.get_input_audio_samplerate()
        block_samples = round(BLOCK_DURATION_S * sample_rate)
        if block_samples <= 0:
            raise ValueError(
                f"get_input_audio_samplerate() returned {sample_rate!r}, "
                "which sizes to a non-positive block; the seam contract "
                "requires a real positive sample rate"
            )
        self._sample_rate = sample_rate
        self._block_samples = block_samples
        preroll_blocks = max(1, math.ceil((PRE_ROLL_S * self._sample_rate) / self._block_samples))
        self._preroll = deque(maxlen=preroll_blocks)
        self._leftover = np.zeros(0, dtype=np.float32)
        self._recording = True

    def stop(self) -> None:
        if not self._recording:
            return
        self._client.stop_recording()
        self._recording = False

    def poll_blocks(self) -> list[npt.NDArray[np.float32]]:
        """Drain whatever is queued right now into complete 32 ms mono blocks.

        ``get_audio_sample()`` hands back one buffer per call - a real
        GStreamer appsink's queue can hold more than one, so this calls
        it in a loop until it returns ``None`` rather than once, or a
        slow-polling caller would fall behind the daemon's own queue.

        Downmixes multi-channel input to mono by taking channel 0 - the
        gap-audit's own G1 section named this as the simpler of its two
        listed options ("channel 0, or the mean"); the Reachy SDK itself
        doesn't document which channel is which, but the legacy driver
        this session ported G2 from does (`legacy-backups/bot-legacy.git:
        robot/robot/hal/drivers/voice.py`'s own comment): the XVF3800's
        default firmware sends two processed channels, 0 the Conference
        tuning, 1 the ASR tuning, and channel 0 measured better for wake
        word on the legacy bench (0.9986). Channel 0 was already the
        right choice here by that evidence, found after the fact, not
        before - averaging would still risk blending in a differently-
        tuned second channel for no benefit. Returns ``[]``, never
        ``None``, when nothing new is queued.
        """
        # Collected into a list and concatenated once at the end, not
        # re-concatenated on every loop iteration: a real queue backlog of
        # many small buffers would otherwise copy the whole growing buffer
        # each time, turning a catch-up poll into O(n^2) work.
        chunks = [self._leftover]
        while True:
            sample = self._client.get_audio_sample()
            if sample is None:
                break
            mono = sample[:, 0] if sample.ndim == 2 else sample
            chunks.append(mono.astype(np.float32))
        buffer = np.concatenate(chunks)
        n_blocks = len(buffer) // self._block_samples
        blocks: list[npt.NDArray[np.float32]] = []
        for i in range(n_blocks):
            block = buffer[i * self._block_samples : (i + 1) * self._block_samples]
            blocks.append(block)
            self._preroll.append(block)
        self._leftover = buffer[n_blocks * self._block_samples :]
        return blocks

    def preroll(self) -> npt.NDArray[np.float32]:
        """The last ~0.3 s of audio, oldest first - what should precede
        the first real speech block in an endpointed utterance (G3)."""
        if not self._preroll:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(list(self._preroll))
