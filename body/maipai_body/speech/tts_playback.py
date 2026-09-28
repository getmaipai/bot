"""G7: the reply, spoken - streamed from the hub, resampled, pushed.

Mirrors the browser's own reference player
(`home/frontend/src/lib/streamingWavPlayer.ts`): parse only the
44-byte WAV header for `sampleRate`/`numChannels`/`bitsPerSample`,
never trust the header's declared data-chunk size (Pocket TTS writes a
placeholder there - the same file's own comment), start pushing audio
as soon as there's enough of it, and end when the stream ends. The
`speak` cue's rendering itself (the low-amplitude sway modulated by
the playback ledger's own audio energy, design record section 5) is
already registered from EXPR-01; this module's job is only to get real
audio into that ledger, in order, resampled correctly - not to render
anything.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt
import requests
from scipy.signal import resample_poly

from maipai_body.speech.playback import AudioPlayback

logger = logging.getLogger("maipai_body.speech.tts_playback")

_WAV_HEADER_BYTES = 44
# Small enough that speech starts almost immediately (the whole point
# of streaming); large enough to avoid pushing hundreds of tiny
# chunks for one reply - matches the browser reference player's own
# MIN_BUFFER_BYTES.
_MIN_BUFFER_BYTES = 4_096


class TtsLinkLost(RuntimeError):
    """The HTTP connection itself failed mid-stream."""


class TtsAuthFailed(RuntimeError):
    """The session cookie was rejected (401)."""


@dataclass
class TtsResult:
    kind: Literal["done", "cancelled", "error"]
    error: str | None = None
    first_chunk_pushed: bool = False


def _parse_wav_header(header: bytes) -> tuple[int, int, int]:
    """Returns (sample_rate, channels, bits_per_sample) - the same three
    fields the browser reference player reads, at the same byte
    offsets (a standard 44-byte WAV/RIFF header: numChannels at 22,
    sampleRate at 24, bitsPerSample at 34, all little-endian)."""
    channels = int.from_bytes(header[22:24], "little")
    sample_rate = int.from_bytes(header[24:28], "little")
    bits_per_sample = int.from_bytes(header[34:36], "little")
    return sample_rate, channels, bits_per_sample


def _pcm16_to_float32(raw: bytes, channels: int) -> npt.NDArray[np.float32]:
    ints = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        ints = ints.reshape(-1, channels)[:, 0]  # downmix: first channel, same as G1's capture
    return (ints.astype(np.float32) / 32768.0).astype(np.float32)


def _resample(
    samples: npt.NDArray[np.float32], from_rate: int, to_rate: int
) -> npt.NDArray[np.float32]:
    if from_rate == to_rate or len(samples) == 0:
        return samples
    from math import gcd

    g = gcd(from_rate, to_rate)
    up, down = to_rate // g, from_rate // g
    return resample_poly(samples, up, down).astype(np.float32)


class TtsPlaybackClient:
    """Streams `POST /api/tts`'s reply into `playback` as it arrives."""

    def __init__(
        self,
        base_url: str,
        session_cookie: str,
        playback: AudioPlayback,
        *,
        session: requests.Session | None = None,
    ) -> None:
        if not session_cookie:
            raise ValueError("session_cookie is empty - the hub link isn't paired yet")
        self._base_url = base_url
        self._cookie = session_cookie
        self._playback = playback
        self._session = session or requests.Session()

    def speak(
        self,
        text: str,
        *,
        on_first_chunk=None,
        stop_event: threading.Event | None = None,
    ) -> TtsResult:
        """Blocks until the reply has fully streamed and been pushed
        through `playback`, or a terminal failure. `on_first_chunk` (if
        given) is called once, the instant the first real audio chunk
        is pushed - the SPEAK cue's own stamp must precede that call,
        not follow it (the design's own onset ordering: expression
        before the first audio sample). `stop_event` (if given and set
        mid-stream - G8's own barge-in) stops pushing further chunks and
        returns `kind="cancelled"`; the ledger keeps whatever prefix was
        already pushed, exactly as `AudioPlayback.stop()`'s own contract
        already promises."""
        try:
            # A context manager, not a bare call: every exit path (a
            # 401, any other non-2xx, an unsupported header, a normal
            # finish, an exception) must close the response - a review
            # caught three of those paths leaking the connection back
            # to the pool unclosed because only the stop_event branch
            # inside _stream_into_playback called close() explicitly.
            with self._session.post(
                f"{self._base_url}/api/tts",
                json={"text": text},
                headers={"Cookie": f"session={self._cookie}"},
                stream=True,
                timeout=(10, 120),
            ) as response:
                if response.status_code == 401:
                    raise TtsAuthFailed(f"hub rejected the tts request: {response.text[:200]}")
                response.raise_for_status()
                return self._stream_into_playback(response, on_first_chunk, stop_event)
        except (TtsLinkLost, TtsAuthFailed):
            raise
        except requests.RequestException as exc:
            raise TtsLinkLost(f"tts connection failed: {exc}") from exc

    def _stream_into_playback(
        self,
        response: requests.Response,
        on_first_chunk,
        stop_event: threading.Event | None,
    ) -> TtsResult:
        header = b""
        leftover = b""  # an incomplete trailing multi-channel frame, held for the next chunk
        sample_rate = channels = bits_per_sample = None
        output_rate = self._playback.output_samplerate()
        first_chunk_pushed = False

        for chunk in response.iter_content(chunk_size=_MIN_BUFFER_BYTES):
            if stop_event is not None and stop_event.is_set():
                return TtsResult(kind="cancelled", first_chunk_pushed=first_chunk_pushed)
            if not chunk:
                continue
            if sample_rate is None:
                header += chunk
                if len(header) < _WAV_HEADER_BYTES:
                    continue
                sample_rate, channels, bits_per_sample = _parse_wav_header(header)
                if bits_per_sample != 16:
                    return TtsResult(
                        kind="error", error=f"unsupported bits_per_sample: {bits_per_sample}"
                    )
                pcm = header[_WAV_HEADER_BYTES:]
                header = b""
            else:
                pcm = chunk

            pcm = leftover + pcm
            if not pcm:
                continue
            # A chunk boundary isn't guaranteed to land on a whole
            # multi-channel frame (channels * 2 bytes) - only on a whole
            # sample (2 bytes) for mono. Truncating to just an even byte
            # count (the original version of this code) let a stereo-or-
            # wider stream's reshape() in _pcm16_to_float32 raise on a
            # partial trailing frame; truncating to whole frames and
            # carrying the remainder to the next chunk, the same pattern
            # G1's own capture.py uses for its leftover samples, is what
            # actually avoids that.
            frame_bytes = 2 * channels
            usable = len(pcm) - (len(pcm) % frame_bytes)
            leftover = pcm[usable:]
            if usable == 0:
                continue
            samples = _pcm16_to_float32(pcm[:usable], channels)
            resampled = _resample(samples, sample_rate, output_rate)
            if len(resampled) == 0:
                continue
            self._playback.push(resampled)
            if not first_chunk_pushed:
                first_chunk_pushed = True
                if on_first_chunk is not None:
                    on_first_chunk()

        return TtsResult(kind="done", first_chunk_pushed=first_chunk_pushed)
