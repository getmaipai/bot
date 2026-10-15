"""StackChan audio turn bridge to the existing hub speech clients."""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading

import av
import numpy as np
import numpy.typing as npt

from maipai_body.speech.capture import BLOCK_SAMPLES
from maipai_body.speech.offline_clips import UNREACHABLE
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.stt_stream import SttStreamClient
from maipai_body.speech.tts_playback import TtsAuthFailed, TtsPlaybackClient
from maipai_body.speech.turn_client import TurnAuthFailed, TurnClient, TurnLinkLost

LOG = logging.getLogger(__name__)


class StackChanAudioCapture:
    """AudioCapture protocol fed by decoded xiaozhi Opus frames."""

    def __init__(self) -> None:
        self._queue: queue.Queue[npt.NDArray[np.float32] | None] = queue.Queue()
        self._closed = threading.Event()
        self._aborted = threading.Event()
        self._decoder = av.CodecContext.create("opus", "r")
        self._resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
        self._leftover = np.zeros(0, dtype=np.float32)

    def feed_opus(self, data: bytes) -> None:
        if self._closed.is_set():
            return
        packet = av.Packet(data)
        for frame in self._decoder.decode(packet):
            for converted in self._resampler.resample(frame):
                samples = converted.to_ndarray().reshape(-1).astype(np.float32)
                self._queue_blocks(samples)

    def _queue_blocks(self, samples: npt.NDArray[np.float32]) -> None:
        data = np.concatenate((self._leftover, samples))
        while len(data) >= BLOCK_SAMPLES:
            self._queue.put(data[:BLOCK_SAMPLES].copy())
            data = data[BLOCK_SAMPLES:]
        self._leftover = data

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.close()

    def close(self) -> None:
        self._closed.set()
        self._queue.put(None)

    def abort(self) -> None:
        self._aborted.set()
        self.close()

    def poll_blocks(self) -> list[npt.NDArray[np.float32]]:
        if self._aborted.is_set():
            raise RuntimeError("StackChan listening was aborted")
        if self._closed.is_set() and self._queue.empty():
            return [np.zeros(BLOCK_SAMPLES, dtype=np.float32)]
        try:
            first = self._queue.get(timeout=0.05)
        except queue.Empty:
            return []
        if first is None:
            self._closed.set()
            return [np.zeros(BLOCK_SAMPLES, dtype=np.float32)]
        blocks = [first]
        while len(blocks) < 8:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                self._closed.set()
                break
            blocks.append(item)
        return blocks


class StackChanAudioPlayback(AudioPlayback):
    """AudioPlayback protocol encoder to authenticated XiaozhiServer.send_audio."""

    def __init__(self, server, device_id: str) -> None:
        self._server = server
        self._device_id = device_id
        self._encoder = self._new_encoder()
        self._samples = np.zeros(0, dtype=np.float32)
        self._frames: list[bytes] = []
        self._lock = threading.RLock()
        self._sentence_start = True
        super().__init__(self)

    def get_output_audio_samplerate(self) -> int:
        return 24000

    @staticmethod
    def _new_encoder():
        encoder = av.CodecContext.create("opus", "w")
        encoder.sample_rate = 24000
        encoder.layout = "mono"
        encoder.format = "s16"
        encoder.options = {"application": "audio", "frame_duration": "60"}
        encoder.open()
        return encoder

    def get_input_audio_samplerate(self) -> int:
        return 16000

    def get_doa(self):
        return None

    def start_recording(self):
        pass

    def stop_recording(self):
        pass

    def get_audio_sample(self):
        return None

    def start_playing(self):
        pass

    def push_audio_sample(self, data: npt.NDArray[np.float32]) -> None:
        with self._lock:
            self._samples = np.concatenate((self._samples, data.astype(np.float32)))
            while len(self._samples) >= 1440:
                block, self._samples = self._samples[:1440], self._samples[1440:]
                frame = av.AudioFrame.from_ndarray(
                    np.clip(block * 32767, -32768, 32767).astype(np.int16).reshape(1, -1),
                    format="s16",
                    layout="mono",
                )
                frame.sample_rate = 24000
                self._frames.extend(bytes(packet) for packet in self._encoder.encode(frame))

    def stop_playing(self) -> None:
        with self._lock:
            if len(self._samples):
                padded = np.pad(self._samples, (0, 1440 - len(self._samples)))
                frame = av.AudioFrame.from_ndarray(
                    np.clip(padded * 32767, -32768, 32767).astype(np.int16).reshape(1, -1),
                    format="s16",
                    layout="mono",
                )
                frame.sample_rate = 24000
                self._frames.extend(bytes(packet) for packet in self._encoder.encode(frame))
            self._frames.extend(bytes(packet) for packet in self._encoder.encode(None))
            frames, self._frames = self._frames, []
            self._samples = np.zeros(0, dtype=np.float32)
            self._encoder = self._new_encoder()
        if frames:
            asyncio.run_coroutine_threadsafe(
                self._server.send_audio(
                    self._device_id,
                    frames,
                    sentence_start=True,
                    start=self._sentence_start,
                    stop=False,
                ),
                self._server._loop,
            ).result(timeout=30)
            self._sentence_start = False

    def end(self) -> None:
        asyncio.run_coroutine_threadsafe(
            self._server.stop_audio(self._device_id), self._server._loop
        ).result(timeout=5)

    def flush(self) -> None:
        with self._lock:
            self._samples = np.zeros(0, dtype=np.float32)
            self._frames.clear()
            self._encoder = self._new_encoder()
        asyncio.run_coroutine_threadsafe(
            self._server.stop_audio(self._device_id), self._server._loop
        )


class StackChanTurnBridge:
    def __init__(
        self,
        server,
        link,
        offline,
        *,
        cache_dir=None,
        stt_factory=SttStreamClient,
        turn_factory=TurnClient,
        tts_factory=TtsPlaybackClient,
        person_attribution=None,
        expression_sink=None,
    ) -> None:
        self.server, self.link, self.offline = server, link, offline
        self.cache_dir = cache_dir
        self.stt_factory, self.turn_factory, self.tts_factory = (
            stt_factory,
            turn_factory,
            tts_factory,
        )
        self.person_attribution = person_attribution or (lambda: None)
        self.expression_sink = expression_sink
        self._captures: dict[str, StackChanAudioCapture] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._playbacks: dict[str, StackChanAudioPlayback] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._settled_sessions: set[str] = set()

    async def on_audio(self, session_id: str, data: bytes) -> None:
        capture = self._captures.get(session_id)
        if capture is not None:
            try:
                capture.feed_opus(data)
            except Exception:
                LOG.exception("StackChan Opus input could not be decoded")

    async def listen(self, session_id: str, device_id: str, state: str) -> None:
        if state in {"start", "detect"}:
            self.abort(session_id)
            capture = StackChanAudioCapture()
            self._captures[session_id] = capture
            task = asyncio.create_task(self._run(session_id, device_id, capture))
            self._tasks[session_id] = task
        elif state == "stop":
            capture = self._captures.get(session_id)
            if capture:
                capture.close()
        elif state == "abort":
            self.abort(session_id)

    def abort(self, session_id: str) -> None:
        capture = self._captures.pop(session_id, None)
        if capture:
            capture.abort()
        cancel = self._cancel_events.get(session_id)
        if cancel:
            cancel.set()
        playback = self._playbacks.get(session_id)
        if playback:
            playback.flush()
        task = self._tasks.pop(session_id, None)
        if task:
            task.cancel()
        self._settled_sessions.add(session_id)
        self._emit_expression("settle")

    def _emit_expression(self, state: str, *, mood: str | None = None) -> None:
        if self.expression_sink is None:
            return
        try:
            self.expression_sink(state, mood=mood)
        except Exception:
            LOG.warning("StackChan expression event failed", exc_info=True)

    def _speaker_evidence(self) -> dict | None:
        try:
            attribution = self.person_attribution()
        except Exception:
            LOG.warning("StackChan person attribution failed", exc_info=True)
            return None
        if not attribution:
            return None
        if isinstance(attribution, dict):
            person_id = attribution.get("person_id")
            confidence = attribution.get("confidence")
            basis = attribution.get("basis", "voice")
            level = attribution.get("level", confidence)
        else:
            person_id = getattr(attribution, "person_id", None)
            confidence = getattr(attribution, "confidence", None)
            basis = getattr(attribution, "basis", "voice")
            level = getattr(attribution, "level", confidence)
        if not person_id or confidence is None:
            return None
        return {"person": person_id, "basis": basis, "level": level}

    async def _run(self, session_id: str, device_id: str, capture: StackChanAudioCapture) -> None:
        playback = StackChanAudioPlayback(self.server, device_id)
        self._playbacks[session_id] = playback
        cancel_event = threading.Event()
        self._cancel_events[session_id] = cancel_event
        self._emit_expression("listening")
        self._settled_sessions.discard(session_id)
        try:
            cookie = self.link.hub_client.session_cookie
            pairing = self.link.pairing_store.load()
            base = getattr(self.link.hub_client, "active_base_url", None) or (
                pairing.base_url if pairing else None
            )
            if not cookie or not base:
                self._emit_expression("thinking")
                await asyncio.to_thread(self._offline_line, playback)
                return
            stt = self.stt_factory(base, cookie)
            result = await asyncio.to_thread(stt.run, capture)
            self._emit_expression("thinking")
            if result.kind != "final" or not result.text:
                await asyncio.to_thread(self._speak_plain_error, playback, base, cookie)
                return
            turn = self.turn_factory(base, cookie)
            events = await asyncio.to_thread(
                lambda: list(turn.stream(result.text, speaker_evidence=self._speaker_evidence()))
            )
            reply = next((e.reply_text for e in reversed(events) if e.reply_text), None)
            if reply:
                tts = self.tts_factory(base, cookie, playback)
                moods = [
                    getattr(getattr(event, "cue", None), "expressed_emotion", None)
                    for event in events
                ]
                mood = next((value for value in reversed(moods) if value), None)
                if mood:
                    self._emit_expression("reply_mood", mood=mood)
                for sentence in _sentences(reply):
                    if asyncio.current_task().cancelling():
                        return
                    self._emit_expression("speaking")
                    await asyncio.to_thread(tts.speak, sentence, stop_event=cancel_event)
                    if cancel_event.is_set():
                        return
                    playback.stop()
                await asyncio.to_thread(playback.end)
            else:
                await asyncio.to_thread(self._speak_plain_error, playback, base, cookie)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("StackChan voice turn failed: %s", type(exc).__name__)
            if isinstance(exc, (TurnAuthFailed, TurnLinkLost, TtsAuthFailed)):
                await asyncio.to_thread(self._offline_line, playback)
            else:
                await asyncio.to_thread(self._speak_plain_error, playback, base, cookie)
        finally:
            if session_id not in self._settled_sessions:
                self._emit_expression("settle")
            self._settled_sessions.discard(session_id)
            self._captures.pop(session_id, None)
            self._tasks.pop(session_id, None)
            self._playbacks.pop(session_id, None)
            self._cancel_events.pop(session_id, None)

    def _offline_line(self, playback) -> None:
        try:
            from pathlib import Path

            from maipai_body.speech.offline_clips import OfflineSpeaker, ensure_clip_bundle

            cache = self.cache_dir or (Path.home() / ".cache" / "maipai-body")
            speaker = OfflineSpeaker(ensure_clip_bundle(cache), playback)
            speaker.say_phrase(UNREACHABLE)
            playback.stop()
            playback.end()
        except Exception:
            LOG.warning("StackChan offline line is unavailable; install the verified clip bundle")

    def _speak_plain_error(self, playback, base: str, cookie: str) -> None:
        try:
            self.tts_factory(base, cookie, playback).speak(
                "I couldn't understand that. Please try again."
            )
            playback.stop()
            playback.end()
        except Exception:
            self._offline_line(playback)


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]
