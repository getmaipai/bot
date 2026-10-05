"""Pieces for driving a real ``ConversationLoop`` against a stand-in hub on a bench.

Audio is the one seam faked here, on purpose: the daemon is started with
``--no-media`` so the real client's audio calls return nothing rather than
reaching the host's real microphone or speaker (a test or a measurement
never takes hardware it does not need, and the simulator's microphone
fallback would otherwise open the host's mic with no consent prompt).
Everything else, the head, tracking, the expression engine, the hub
clients, is the real thing.
"""

from __future__ import annotations

import threading

import numpy as np
import numpy.typing as npt


class NullAudioIO:
    """Wraps a real `ReachyMiniClient`: every HAL call other than audio
    goes straight to it (attribute delegation via `__getattr__`); audio
    is faked entirely (see this file's own header on why)."""

    def __init__(self, real_client) -> None:
        self._real = real_client
        self._recording = False
        self.pushed: list[npt.NDArray[np.float32]] = []

    def __getattr__(self, name):
        # A review (2026-09-28) named the footgun: reading `self._real`
        # directly here recurses back into `__getattr__` (RecursionError,
        # not a clean AttributeError) if anything ever probes an
        # attribute before `__init__`'s first line runs. Not reachable
        # today (nothing subclasses or pickles this), but one guard is
        # cheap insurance against a confusing failure mode later.
        if name == "_real":
            raise AttributeError(name)
        return getattr(self._real, name)

    def start_recording(self) -> None:
        self._recording = True

    def stop_recording(self) -> None:
        self._recording = False

    def get_audio_sample(self) -> npt.NDArray[np.float32] | None:
        if not self._recording:
            return None
        return np.zeros(512, dtype=np.float32)  # one 32ms block's worth of silence

    def get_input_audio_samplerate(self) -> int:
        return 16000

    def start_playing(self) -> None:
        pass

    def push_audio_sample(self, data: npt.NDArray[np.float32]) -> None:
        self.pushed.append(data)

    def stop_playing(self) -> None:
        pass

    def get_output_audio_samplerate(self) -> int:
        return 16000

    def get_doa(self):
        return None


class TriggerableWakeEngine:
    """Scores 0 until `trigger()` is called; then the next `score()`
    call returns 1.0. `reset()` (WakeScorer's own post-wake contract,
    called the instant it returns an event) re-arms this for the next
    turn - real audio content is never scored, since there is none."""

    def __init__(self) -> None:
        self._fire = threading.Event()

    def trigger(self) -> None:
        self._fire.set()

    def score(self, block: npt.NDArray[np.float32]) -> float:
        return 1.0 if self._fire.is_set() else 0.0

    def reset(self) -> None:
        self._fire.clear()
