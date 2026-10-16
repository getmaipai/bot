"""VOICE-01 / VOICE-02: the robot's one speech process.

Wake, voice activity, endpointing, speech to text, synthesis and the ledger
of what was actually spoken, in one object over the seam's ``AudioIO``. The
legacy robot fixed three things on its bench and they live here, ported in
shape from ``legacy-backups/bot-legacy.git:robot/robot/hal/drivers/voice.py``:

* **Pre-roll.** Moonshine tiny returns nothing behind half a second of silent
  head, so while waiting for the sentence only the last ``PRE_ROLL_S`` of
  audio is kept, never the audio from the wake word on.
* **Retry from the onset block.** An empty transcript is retried once from the
  block where the VAD first heard speech.
* **The tail-syllable rule.** The end of the wake phrase can trip the VAD and
  the talker's pause then closes a "turn" holding a syllable and silence. An
  empty transcript inside the wake patience window is a false start, not a
  turn: keep listening. Patience (``WAKE_PATIENCE_S``) still bounds the window.

Audio never leaves this object as frames. The runtime sees ``VoiceEvent``s and
hands back text to :meth:`SpeechProcess.speak`; ``voice_server.py`` serves that
over the voice contract. All timing here is audio time (blocks of 32 ms), so a
fake microphone runs it as fast as the CPU allows.

Speaking is paced to the clock so the ledger records what was heard, not what
was queued in the output stream, and the capture keeps being read while the
robot talks so a stop word (VOICE-02) cuts playback within one block.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import numpy.typing as npt

from maipai_body.hal.seam import AudioIO, DirectionOfArrival
from maipai_body.speech.capture import BLOCK_DURATION_S, PRE_ROLL_S, AudioCapture
from maipai_body.speech.engines import (
    SpeakerEmbedder,
    StopDetector,
    SttEngine,
    TtsEngine,
    VadEngine,
)
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.stt_stream import WAKE_PATIENCE_S
from maipai_body.speech.tts_playback import resample_audio
from maipai_body.speech.wake import WakeScorer

logger = logging.getLogger("maipai_body.speech.process")

SAMPLE_RATE = 16000
TRAILING_SILENCE_S = 0.7  # the fixed-timeout endpoint (legacy value)
MAX_UTTERANCE_S = 12.0  # a hard stop so a noisy room cannot record forever
# How far ahead of the clock playback may be queued. The ledger counts audio as
# heard once its time has passed, so a stop never claims more than was played.
PLAYBACK_LEAD_S = 0.1
_SERVICE_SLEEP_S = 0.005


@dataclass(frozen=True)
class VoiceEvent:
    """What the runtime is told. Never carries audio."""

    kind: Literal["wake", "speech_start", "speech_end", "utterance", "no_speech"]
    text: str | None = None
    doa: DirectionOfArrival | None = None
    score: float | None = None
    note: str | None = None
    speech_s: float | None = None  # seconds from onset to the last speech block


@dataclass
class SegmentRecord:
    text: str
    duration_s: float


@dataclass
class SpokenRecord:
    """One reply as it was actually spoken (the ledger row).

    ``spoken_prefix`` is the words the listener heard: every sentence whose
    audio had fully played, plus the whole words of the sentence being cut,
    rounded down. It never claims a word that had not played."""

    text: str
    voice_id: str
    segments: list[SegmentRecord] = field(default_factory=list)
    heard_s: float = 0.0
    completed: bool = False
    cancelled: bool = False
    cancel_reason: str | None = None
    spoken_prefix: str = ""
    turn_id: str | None = None


def spoken_prefix(segments: list[SegmentRecord], heard_s: float) -> str:
    out: list[str] = []
    remaining = heard_s
    for seg in segments:
        words = seg.text.split()
        if seg.duration_s <= 0:
            continue
        if remaining >= seg.duration_s - 1e-9:
            out.append(seg.text.strip())
            remaining -= seg.duration_s
            continue
        count = math.floor(len(words) * max(remaining, 0.0) / seg.duration_s)
        if count:
            out.append(" ".join(words[:count]))
        break
    return " ".join(out)


class SpeechProcess:
    def __init__(
        self,
        *,
        audio: AudioIO,
        capture: AudioCapture,
        wake: WakeScorer,
        vad: VadEngine,
        stt: SttEngine,
        playback: AudioPlayback | None = None,
        tts: TtsEngine | None = None,
        embedder: SpeakerEmbedder | None = None,
        stop_detector: StopDetector | None = None,
        normalizer: Callable[[str], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._audio = audio
        self._capture = capture
        self._wake = wake
        self._vad = vad
        self._stt = stt
        self.playback = playback
        self.tts = tts
        self.embedder = embedder
        self._stop_detector = stop_detector
        self._normalize = normalizer or (lambda text: text)
        self._clock = clock
        self._sleep = sleep
        self._preroll_blocks = max(1, math.ceil(PRE_ROLL_S / BLOCK_DURATION_S))
        self._listening = False
        self._speaking = False
        self._patience_s = WAKE_PATIENCE_S
        self._reset_utterance()
        self._doa: DirectionOfArrival | None = None
        self.last_utterance: npt.NDArray[np.float32] | None = None  # RAM only, replaced each time
        self.spoken_ledger: list[SpokenRecord] = []
        self._ledger_lock = threading.Lock()
        self.self_wakes = 0  # wakes scored while the robot itself was speaking (always 0 by design)

    # -- state ---------------------------------------------------------------

    @property
    def listening(self) -> bool:
        return self._listening

    @property
    def speaking(self) -> bool:
        return self._speaking

    def _reset_utterance(self) -> None:
        self._buffer: list[npt.NDArray[np.float32]] = []
        self._heard_speech = False
        self._onset_block = 0
        self._last_speech_block = 0
        self._silence_s = 0.0
        self._elapsed_s = 0.0

    def listen_again(self, patience_s: float | None = None) -> None:
        """Open the listen window without a wake word (the follow-up window, a
        barge-in arm). While still waiting for speech it only re-bounds the
        wait; mid-capture it is a no-op."""
        patience = WAKE_PATIENCE_S if patience_s is None else patience_s
        if self._listening:
            if not self._heard_speech:
                self._patience_s = patience
                self._elapsed_s = 0.0
            return
        self._patience_s = patience
        self._begin_listening()

    def _begin_listening(self) -> None:
        self._listening = True
        self._reset_utterance()
        self._vad.reset()

    def _asleep(self) -> None:
        self._listening = False
        self._doa = None
        self._reset_utterance()

    # -- listening -----------------------------------------------------------

    def step(self) -> list[VoiceEvent]:
        """Pull one buffer of audio and run its blocks through the pipeline."""
        if self._speaking:
            return []  # speak() owns the capture while the robot talks
        events: list[VoiceEvent] = []
        for block in self._capture.poll_blocks():
            events.extend(self._step_block(block))
        return events

    def _step_block(self, block: npt.NDArray[np.float32]) -> list[VoiceEvent]:
        if not self._listening:
            wake = self._wake.poll(block)
            if wake is None:
                return []
            self._patience_s = WAKE_PATIENCE_S
            self._begin_listening()
            self._doa = wake.doa
            return [VoiceEvent(kind="wake", doa=wake.doa, score=wake.score)]

        self._elapsed_s += BLOCK_DURATION_S
        self._buffer.append(block)
        events: list[VoiceEvent] = []
        if self._vad.is_speech(block):
            self._silence_s = 0.0
            self._last_speech_block = len(self._buffer) - 1
            if not self._heard_speech:
                self._heard_speech = True
                self._onset_block = len(self._buffer) - 1
                # The beams have had time to focus since the wake word.
                self._doa = self._audio.get_doa() or self._doa
                events.append(VoiceEvent(kind="speech_start", doa=self._doa))
        else:
            self._silence_s += BLOCK_DURATION_S
            if not self._heard_speech and len(self._buffer) > self._preroll_blocks:
                del self._buffer[: len(self._buffer) - self._preroll_blocks]

        if self._heard_speech and self._silence_s >= TRAILING_SILENCE_S:
            return events + self._finish()
        if self._elapsed_s >= MAX_UTTERANCE_S:
            return events + (self._finish() if self._heard_speech else self._give_up())
        if not self._heard_speech and self._elapsed_s >= self._patience_s:
            return events + self._give_up()
        return events

    def _give_up(self) -> list[VoiceEvent]:
        self._asleep()
        self._wake_forget()
        return [VoiceEvent(kind="no_speech", note="woken, then heard nothing")]

    def _wake_forget(self) -> None:
        self._wake.reset()  # the phrase that woke us must not wake us again

    def _transcribe(self, samples: npt.NDArray[np.float32]) -> str:
        return (self._stt.transcribe(samples, SAMPLE_RATE) or "").strip()

    def _finish(self) -> list[VoiceEvent]:
        pcm = np.concatenate(self._buffer) if self._buffer else np.zeros(0, np.float32)
        onset_samples = self._onset_block * len(self._buffer[0]) if self._buffer else 0
        speech_s = (
            (self._last_speech_block - self._onset_block + 1) * BLOCK_DURATION_S
            if self._heard_speech
            else 0.0
        )
        out = [VoiceEvent(kind="speech_end")]
        try:
            text = self._transcribe(pcm)
            if not text and 0 < onset_samples < len(pcm):
                text = self._transcribe(pcm[onset_samples:])
        except Exception as exc:  # noqa: BLE001 - a failed transcription must not vanish the turn
            logger.warning("transcription failed: %s", type(exc).__name__)
            self._asleep()
            self._wake_forget()
            return out + [VoiceEvent(kind="no_speech", note="transcription failed")]
        if not text:
            heard = f"transcribed nothing from {len(pcm) / SAMPLE_RATE:.1f}s of audio"
            if self._elapsed_s < self._patience_s:
                # A false start (the wake phrase's tail), not a turn: keep listening.
                self._heard_speech = False
                self._silence_s = 0.0
                self._onset_block = 0
                self._last_speech_block = 0
                keep = self._buffer[-self._preroll_blocks :]
                self._buffer = list(keep)
                self._vad.reset()
                return out + [VoiceEvent(kind="no_speech", note=f"{heard}; still listening")]
            self._asleep()
            self._wake_forget()
            return out + [VoiceEvent(kind="no_speech", note=heard)]
        self.last_utterance = pcm
        doa = self._doa
        self._asleep()
        self._wake_forget()
        return out + [VoiceEvent(kind="utterance", text=text, doa=doa, speech_s=speech_s)]

    # -- speaking ------------------------------------------------------------

    def speak(
        self,
        text: str,
        *,
        turn_id: str | None = None,
        on_barge: Callable[[], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> SpokenRecord:
        """Say ``text`` through the line-out and return its ledger row.

        The capture is read between pushes; a ``StopDetector`` hit (VOICE-02)
        or ``stop_event`` stops the output within one 32 ms block, runs
        ``on_barge`` (the runtime's cancel) and leaves the exact spoken prefix
        in the row. The wake scorer is not fed while the robot speaks."""
        if self.playback is None or self.tts is None:
            raise RuntimeError("this speech process has no playback or voice to speak with")
        spoken_text = self._normalize(text)
        record = SpokenRecord(text=spoken_text, voice_id=self.tts.voice_id, turn_id=turn_id)
        with self._ledger_lock:
            self.spoken_ledger.append(record)
        self._speaking = True
        if self._stop_detector is not None:
            self._stop_detector.reset()
        out_rate = self.playback.output_samplerate()
        step = max(1, round(BLOCK_DURATION_S * out_rate))
        t0 = self._clock()
        pushed_s = 0.0
        stopped: str | None = None
        try:
            self.playback.start()
            for segment in self.tts.synthesize(spoken_text):
                samples = resample_audio(segment.samples, segment.sample_rate, out_rate)
                record.segments.append(
                    SegmentRecord(text=segment.text, duration_s=len(samples) / out_rate)
                )
                for i in range(0, len(samples), step):
                    stopped = self._service(stop_event)
                    while stopped is None and pushed_s - (self._clock() - t0) > PLAYBACK_LEAD_S:
                        self._sleep(_SERVICE_SLEEP_S)
                        stopped = self._service(stop_event)
                    if stopped is not None:
                        break
                    chunk = samples[i : i + step]
                    self.playback.push(chunk)
                    pushed_s += len(chunk) / out_rate
                if stopped is not None:
                    break
            while stopped is None and (self._clock() - t0) < pushed_s:  # let the tail play
                self._sleep(_SERVICE_SLEEP_S)
                stopped = self._service(stop_event)
        finally:
            heard = min(pushed_s, max(self._clock() - t0, 0.0))
            if stopped is not None:
                record.heard_s = heard
                record.cancelled = True
                record.cancel_reason = stopped
                self.playback.stop()
            else:
                record.heard_s = pushed_s
                record.completed = True
                self.playback.stop()
            record.spoken_prefix = spoken_prefix(record.segments, record.heard_s)
            self._speaking = False
        if record.cancelled and on_barge is not None:
            try:
                on_barge()
            except Exception:  # noqa: BLE001 - the local cut already happened
                logger.warning("barge-in cancel callback failed", exc_info=True)
        return record

    def _service(self, stop_event: threading.Event | None) -> str | None:
        """Read the capture and ask the stop detector; why to stop, or ``None``."""
        if stop_event is not None and stop_event.is_set():
            return "stop_event"
        if self._stop_detector is None:
            return None
        for block in self._capture.poll_blocks():
            if self._stop_detector.accept(block):
                return "stop_word"
        return None

    # -- the embedder --------------------------------------------------------

    def embed_last(self) -> npt.NDArray[np.float32] | None:
        """The CAM++ embedding of the last utterance, or ``None``. SPEAK-01's input."""
        if self.embedder is None or self.last_utterance is None:
            return None
        return self.embedder.embed(self.last_utterance, SAMPLE_RATE)
