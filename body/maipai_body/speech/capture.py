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
    caller likes (a tight loop, a timer tick); each call pulls one
    buffer and returns zero or more *complete* 32 ms mono blocks,
    holding any leftover samples for the next call rather than padding
    or dropping them. See :meth:`poll_blocks`'s own docstring for why
    this deliberately does not try to drain more than one buffer per
    call against a live stream.
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
        """Pull one buffer and re-chunk whatever that completes.

        Calls ``get_audio_sample()`` exactly once, not in a loop until
        ``None`` - live-verified (2026-09-28, against the real
        `reachy-mini-daemon --sim`) that this must NOT loop: the real
        appsink's own pull (`reachy_mini/media/gstreamer_utils.py`'s
        `get_sample()`) blocks for up to a real 20 ms waiting for the
        next buffer, and a continuously-recording microphone almost
        always has one within that window - `None` essentially never
        happens while the mic is live, so a "drain until None" loop
        blocks forever the moment it catches up to real time, one 20 ms
        wait after another, never returning to the caller. (An earlier
        version of this method did loop that way, added by a review that
        reasoned correctly about a real backlog existing but never
        verified the fix against a live continuous stream, only the
        fake's own finite fixture, which legitimately exhausts and hits
        `None` for a different reason.) The seam's own docstring already
        says `poll_blocks()` should be called "as often as the caller
        likes (a tight loop, a timer tick)" - one pull per call is
        exactly that contract; the appsink's own `max-buffers=200,
        drop=True` config (`reachy_mini/media/audio_gstreamer.py`) is
        the real backpressure mechanism for a caller that polls too
        slowly, not this method looping to compensate. That mechanism
        is lossy, not backoff: a caller whose own per-tick work (wake
        scoring, endpointing) runs consistently slower than the real
        audio arrives silently drops the oldest queued audio once the
        200-buffer cap fills, with nothing here surfacing that loss -
        worth naming as a real constraint on G9's future run loop, not
        assuming "it'll catch up eventually."

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
        sample = self._client.get_audio_sample()
        if sample is None:
            buffer = self._leftover
        else:
            mono = sample[:, 0] if sample.ndim == 2 else sample
            buffer = np.concatenate([self._leftover, mono.astype(np.float32)])
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
