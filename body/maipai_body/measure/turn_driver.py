"""A scripted turn on a clock: a recorded utterance as the microphone, the real hub clients.

M-R1 runs one every two minutes for an hour to load the Compute Module the
way a household would, and reads three latencies off it; M-R4 runs the
same turn as its "in conversation" workload. The audio is a file the
operator supplies, fed at real time pace and followed by silence so the
hub's own endpointing has something to endpoint on; no live microphone is
opened and no household recording is ever read.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from maipai_body.bodies.reachy_mini.fake import _load_wav_as_stereo_16k
from maipai_body.speech.stt_stream import SttStreamClient
from maipai_body.speech.tts_playback import TtsPlaybackClient
from maipai_body.speech.turn_client import TurnClient

_BLOCK_SAMPLES = 512
_RATE = 16_000


def load_utterance(path: Path) -> npt.NDArray[np.float32]:
    """A 16 kHz 16-bit WAV as mono float32 (the first channel, as the capture path does)."""
    return np.ascontiguousarray(_load_wav_as_stereo_16k(path)[:, 0], dtype=np.float32)


class WavCapture:
    """The slice of ``AudioCapture`` the stt client uses, fed from a recording."""

    def __init__(
        self, samples: npt.NDArray[np.float32], *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._samples = samples
        self._clock = clock
        self._started: float | None = None
        self._delivered = 0
        self._real_blocks = -(-len(samples) // _BLOCK_SAMPLES)
        self.end_of_audio_at: float | None = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def poll_blocks(self) -> list[npt.NDArray[np.float32]]:
        now = self._clock()
        if self._started is None:
            self._started = now
            return []
        due = int((now - self._started) * _RATE) // _BLOCK_SAMPLES
        blocks = []
        while self._delivered < due:
            index = self._delivered
            block = np.zeros(_BLOCK_SAMPLES, dtype=np.float32)
            if index < self._real_blocks:
                chunk = self._samples[index * _BLOCK_SAMPLES : (index + 1) * _BLOCK_SAMPLES]
                block[: len(chunk)] = chunk
                if index == self._real_blocks - 1:
                    self.end_of_audio_at = now
            blocks.append(block)
            self._delivered += 1
        return blocks


def run_scripted_turn(
    stt: SttStreamClient,
    turn: TurnClient,
    tts: TtsPlaybackClient,
    *,
    capture_factory: Callable[[], Any],
    clock: Callable[[], float] = time.monotonic,
    speak: bool = True,
) -> dict[str, Any]:
    """One turn: stt, the turn stream, then (unless ``speak`` is off) the spoken reply.

    ``endpoint_to_transcript_ms`` runs from the last sample of the
    utterance to the final transcript, so it includes the hub's own
    endpointing silence; the robot tier is measured the same way, which is
    what makes the two tiers comparable.
    """
    capture = capture_factory()
    result = stt.run(capture)
    transcribed_at = clock()
    if result.kind != "final" or not result.text:
        return {"error": f"stt returned {result.kind}, not a final transcript"}
    endpoint = capture.end_of_audio_at
    row: dict[str, Any] = {
        "endpoint_to_transcript_ms": (
            None if endpoint is None else (transcribed_at - endpoint) * 1e3
        ),
        "transcript_chars": len(result.text),
    }

    turn_started = clock()
    reply = ""
    first_event_at: float | None = None
    for event in turn.stream(result.text):
        if first_event_at is None:
            first_event_at = clock()
        if event.reply_text is not None:
            reply = event.reply_text
    turn_done = clock()
    if first_event_at is not None:
        row["turn_first_event_ms"] = (first_event_at - turn_started) * 1e3
    row["turn_total_ms"] = (turn_done - turn_started) * 1e3

    if speak and reply:
        speak_started = clock()
        first_audio: list[float] = []
        tts.speak(reply, on_first_chunk=lambda: first_audio.append(clock()))
        if first_audio:
            row["tts_first_audio_ms"] = (first_audio[0] - speak_started) * 1e3
    return row
