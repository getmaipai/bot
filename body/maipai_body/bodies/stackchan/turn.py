"""StackChan audio turn bridge to the existing hub speech clients."""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import queue
import re
import threading
import time

import av
import numpy as np
import numpy.typing as npt

from maipai_body.bodies.stackchan.error_line import ErrorLineBreaker
from maipai_body.speaker_evidence import SpeakerEvidenceError, speaker_evidence
from maipai_body.speech.capture import BLOCK_SAMPLES
from maipai_body.speech.offline_clips import UNREACHABLE
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.stt_stream import WAKE_PATIENCE_S, SttStreamClient
from maipai_body.speech.tts_playback import TtsAuthFailed, TtsPlaybackClient
from maipai_body.speech.turn_client import TurnAuthFailed, TurnClient, TurnLinkLost

LOG = logging.getLogger(__name__)
# Frames sent ahead of playback. The firmware's decode queue holds 40 frames (2.4 s) and silently
# drops any packet that arrives when it is full, and a burst that catches up after a late frame
# lands on top of what is queued. A short lead (14 frames, 0.84 s, sent in about 0.2 s) keeps the
# queue near 10 of 40 so even a catch-up cannot overflow it. UNMEASURED on the unit.
LEAD_FRAMES = 14
# More than this many frames behind the schedule: do not burst to catch up, re-base the schedule.
MAX_BEHIND_FRAMES = 2
# Frames in flight (sent minus played at real time) above this are counted as over the soft cap.
IN_FLIGHT_SOFT_CAP = 30
STREAM_POLL_S = 0.01
# The listening pop-up tone plays right after a wake word or a tap and the microphone hears it;
# uplink frames this soon after a listen start are not sent on, so the tone never reaches speech
# recognition (the hub answers one short voiced burst with no_speech). UNMEASURED default.
POPUP_HOLD_S = 0.3
# A listen the device re-opens by itself right after a reply is a follow-up: the person has this
# long to speak before the turn ends quietly (robot.follow_up.seconds, default 8).
FOLLOW_UP_S = 8.0
FOLLOW_UP_AFTER_S = 2.0
# Voiced audio the hub must have called speech before a failure is worth an apology.
MIN_SPEECH_S = 0.5
FRAME_S = 0.06
# Decode and speaker delay after the last frame's play time, before the stop.
STOP_TAIL_S = 0.12


class StackChanAudioCapture:
    """AudioCapture protocol fed by decoded xiaozhi Opus frames."""

    def __init__(self) -> None:
        self._queue: queue.Queue[npt.NDArray[np.float32] | None] = queue.Queue()
        self._closed = threading.Event()
        self._aborted = threading.Event()
        self._decoder = av.CodecContext.create("opus", "r")
        self._resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
        self._leftover = np.zeros(0, dtype=np.float32)
        self.peak = 0.0  # loudest sample seen (0..1); a level, never audio

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def feed_opus(self, data: bytes) -> None:
        if self._closed.is_set():
            return
        packet = av.Packet(data)
        for frame in self._decoder.decode(packet):
            for converted in self._resampler.resample(frame):
                samples = converted.to_ndarray().reshape(-1).astype(np.float32)
                if samples.size:
                    self.peak = max(self.peak, min(1.0, float(np.max(np.abs(samples)))))
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

    def __init__(
        self,
        server,
        device_id: str,
        *,
        clock=time.monotonic,
        sleeper=time.sleep,
        async_sleep=asyncio.sleep,
        pitch_semitones=lambda: 0.0,
    ) -> None:
        self._server = server
        self._device_id = device_id
        # The selected voice's pitch offset in semitones (0 leaves the audio untouched).
        self._pitch_semitones = pitch_semitones
        self._pitch_buffer: list[npt.NDArray[np.float32]] = []
        # Streaming sender state (one sentence at a time).
        self._sender_future: concurrent.futures.Future | None = None
        self._finished = False
        self._sent_frames = 0
        self._lateness: list[float] = []
        self._behind_events = 0
        self._max_in_flight = 0.0
        self._over_cap = 0
        self._encoder = self._new_encoder()
        self._samples = np.zeros(0, dtype=np.float32)
        self._frames: list[bytes] = []
        self._lock = threading.RLock()
        self._sentence_start = True
        self._clock, self._sleep, self._async_sleep = clock, sleeper, async_sleep
        self._cancel_event: threading.Event | None = None
        self._aborted = threading.Event()
        # When the robot finishes playing what was sent; the stop waits for it.
        self._play_until = 0.0
        super().__init__(self)

    def get_output_audio_samplerate(self) -> int:
        return 24000

    @staticmethod
    def _new_encoder():
        encoder = av.CodecContext.create("opus", "w")
        encoder.sample_rate = 24000
        encoder.layout = "mono"
        encoder.format = "s16"
        # Speech-mode SILK wideband: one 60 ms frame per packet at 24 kbps. The default
        # music mode sent 64 kbps packets of three CELT frames, which the ESP32-S3
        # decoded slower than real time (choppy speech on the 2026-10-19 unit bench).
        encoder.bit_rate = 24000
        encoder.options = {"application": "voip", "frame_duration": "60", "cutoff": "8000"}
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
            if self._pitch_semitones() != 0.0:
                # A pitch offset needs the whole sentence (nothing is sent before stop() anyway).
                self._pitch_buffer.append(data.astype(np.float32))
                return
            self._frame_locked(data)

    def _frame_locked(self, data: npt.NDArray[np.float32]) -> None:
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
        self._kick_locked()

    def _cancelled(self) -> bool:
        return self._aborted.is_set() or (
            self._cancel_event is not None and self._cancel_event.is_set()
        )

    def _kick_locked(self) -> None:
        """Start sending as soon as the lead exists, while the sentence is still synthesizing."""
        if (
            self._sender_future is None
            and len(self._frames) >= LEAD_FRAMES
            and getattr(self._server, "_loop", None) is not None
            and not self._cancelled()
        ):
            self._sender_future = asyncio.run_coroutine_threadsafe(
                self._sender(), self._server._loop
            )

    async def _sender(self) -> None:
        """Send the lead at once, then the rest at real time; never burst to catch up."""
        with self._lock:
            lead = self._frames[:LEAD_FRAMES]
            del self._frames[:LEAD_FRAMES]
        if not lead or self._cancelled():
            return
        first_sentence = self._sentence_start
        self._sentence_start = False
        began = self._clock()
        self._play_until = max(self._clock(), self._play_until) + len(lead) * FRAME_S
        await self._server.send_audio(
            self._device_id,
            lead,
            sentence_start=True,
            start=first_sentence,
            stop=False,
            prebuffer=len(lead),
        )
        sent = len(lead)
        self._note_flight(sent, began)
        deadline = self._clock()
        while not self._cancelled():
            with self._lock:
                frame = self._frames.pop(0) if self._frames else None
                finished = self._finished
            if frame is None:
                if finished:
                    break
                await self._async_sleep(STREAM_POLL_S)
                deadline = max(deadline, self._clock())  # a stalled producer: no burst after it
                continue
            deadline += FRAME_S
            now = self._clock()
            behind = (now - deadline) / FRAME_S
            if behind > MAX_BEHIND_FRAMES:
                self._behind_events += 1
                LOG.warning(
                    "StackChan playback behind by %d frames; re-basing the schedule", int(behind)
                )
                deadline = now
            else:
                await self._async_sleep(max(0.0, deadline - now))
            if self._cancelled():
                break
            self._lateness.append(max(0.0, self._clock() - deadline))
            await self._server.send_audio(
                self._device_id, [frame], sentence_start=False, start=False, stop=False
            )
            sent += 1
            self._play_until = max(self._play_until, self._clock()) + FRAME_S
            self._note_flight(sent, began)
        self._sent_frames += sent

    def _note_flight(self, sent: int, began: float) -> None:
        in_flight = sent - (self._clock() - began) / FRAME_S
        self._max_in_flight = max(self._max_in_flight, in_flight)
        if in_flight > IN_FLIGHT_SOFT_CAP:
            self._over_cap += 1

    def _log_sentence_stats(self) -> None:
        late = sorted(self._lateness)
        p95 = late[int(0.95 * (len(late) - 1))] if late else 0.0
        LOG.info(
            "StackChan playback: %d frames, lateness p95 %.0f ms max %.0f ms, behind %d times, "
            "max in flight %.0f, over %d in flight %d times",
            self._sent_frames,
            p95 * 1000,
            (late[-1] if late else 0.0) * 1000,
            self._behind_events,
            self._max_in_flight,
            IN_FLIGHT_SOFT_CAP,
            self._over_cap,
        )

    def _reset_sentence(self) -> None:
        self._sender_future = None
        self._finished = False
        self._sent_frames = 0
        self._lateness = []
        self._behind_events = 0
        self._max_in_flight = 0.0
        self._over_cap = 0

    def stop_playing(self) -> None:
        with self._lock:
            if self._pitch_buffer:
                from maipai_body.speech.pitch import shift_pitch

                whole = np.concatenate(self._pitch_buffer)
                self._pitch_buffer = []
                self._frame_locked(shift_pitch(whole, 24000, self._pitch_semitones()))
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
            self._samples = np.zeros(0, dtype=np.float32)
            self._encoder = self._new_encoder()
            self._finished = True
            if self._sender_future is None and self._frames and not self._cancelled():
                # A short sentence: fewer frames than the lead, so nothing has been sent yet.
                self._sender_future = asyncio.run_coroutine_threadsafe(
                    self._sender(), self._server._loop
                )
            future = self._sender_future
            remaining = len(self._frames)
        try:
            if future is not None:
                try:
                    future.result(timeout=remaining * FRAME_S + 10.0)
                except concurrent.futures.TimeoutError:
                    future.cancel()  # the coroutine must not keep sending in the background
                    raise
            if future is not None:
                self._log_sentence_stats()
        finally:
            with self._lock:
                self._reset_sentence()

    def end(self) -> None:
        # The robot holds up to LEAD_FRAMES of audio when the last frame is sent. Stopping
        # then cut the talking mouth about 1.4 s (four words) early on the 2026-10-19 bench.
        self._sleep(max(0.0, self._play_until - self._clock()) + STOP_TAIL_S)
        asyncio.run_coroutine_threadsafe(
            self._server.stop_audio(self._device_id), self._server._loop
        ).result(timeout=5)

    def flush(self, *, send_stop: bool = True) -> None:
        self._aborted.set()
        with self._lock:
            self._samples = np.zeros(0, dtype=np.float32)
            self._frames.clear()
            self._pitch_buffer = []
            if self._sender_future is not None:
                self._sender_future.cancel()
            self._encoder = self._new_encoder()
        if send_stop:
            return asyncio.run_coroutine_threadsafe(
                self._server.stop_audio(self._device_id), self._server._loop
            )
        return None


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
        live_sink=None,
        uplink_stats=None,
        side_executor=None,
        volume_control=None,
        clock=time.monotonic,
    ) -> None:
        self.server, self.link, self.offline = server, link, offline
        # The light standard's live cue: green while the voice is being sent to the hub.
        self.live_sink = live_sink
        # BOT-SELF-TEST-01: counts of uplink frames and wake detects (never audio).
        self.uplink_stats = uplink_stats
        # "Louder", "volume to 60": answered here, without asking the hub.
        self.volume_control = volume_control
        # The expression and light sinks make blocking device calls that wait on this very event
        # loop; run inline they froze it until each 5 s timeout (live log 2026-10-20: 5 s to start
        # a turn, 12 s to the first audio frame). One worker keeps their order.
        self._side = side_executor or concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="stackchan-side"
        )
        self._clock = clock
        self.cache_dir = cache_dir
        self.stt_factory, self.turn_factory, self.tts_factory = (
            stt_factory,
            turn_factory,
            tts_factory,
        )
        self.person_attribution = person_attribution or (lambda: None)
        self.expression_sink = expression_sink
        self._captures: dict[str, StackChanAudioCapture] = {}
        self._states: dict[str, str] = {}
        self._aec: dict[str, bool] = {}
        self._speech_ended: dict[str, float] = {}
        self._speaking_since: dict[str, float] = {}
        self._uplink_live = 0
        self._uplink_dropped = 0
        self._first_audio_ms: float | None = None
        self._abort_to_silence_ms: float | None = None
        self._abort_started: dict[str, float] = {}
        self._capture_started: dict[str, float] = {}
        self._modes: dict[str, str] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._playbacks: dict[str, StackChanAudioPlayback] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._settled_sessions: set[str] = set()
        # Voice diagnostics (counts only, never audio or words): frames and bytes per session.
        self._audio_stats: dict[str, list[int]] = {}
        self._popup_dropped = 0
        self._current_session = ""
        self._last_turn_end: dict[str, float] = {}
        self._followup: dict[str, bool] = {}
        self.follow_up_s = FOLLOW_UP_S
        # The selected voice record's pitch_semitones (-12 to 12); 0 changes nothing.
        self.pitch_semitones = lambda: 0.0
        self._breaker = ErrorLineBreaker(clock=clock)
        self._quiet_streak = 0

    async def on_audio(self, session_id: str, data: bytes) -> None:
        stats = self._audio_stats.setdefault(session_id, [0, 0])
        stats[0] += 1
        stats[1] += len(data)
        if stats[0] == 1:
            LOG.info(
                "StackChan voice: first audio frame (%d bytes) for session %s",
                len(data),
                session_id[:8],
            )
        capture = self._captures.get(session_id)
        self._record_uplink(len(data), getattr(capture, "peak", 0.0))
        now = self._clock()
        if self._states.get(session_id) == "speaking":
            if not self._aec.get(session_id, False):
                self._uplink_dropped += 1
                return
            self._uplink_live += 1
        elif now - self._speech_ended.get(session_id, float("-inf")) < 0.18:
            self._uplink_dropped += 1
            return
        if capture is not None and now - self._capture_started.get(session_id, -1e9) < POPUP_HOLD_S:
            self._popup_dropped += 1
            return
        if capture is not None:
            started = self._capture_started.get(session_id, now)
            if self._first_audio_ms is None:
                self._first_audio_ms = max(0.0, (now - started) * 1000)
            try:
                # Decoding and resampling run off the event loop (one frame at a time, in order):
                # inline they delayed the paced send's wake-ups.
                await asyncio.to_thread(capture.feed_opus, data)
            except Exception:
                LOG.exception("StackChan Opus input could not be decoded")

    async def listen(
        self, session_id: str, device_id: str, state: str, *, mode="auto", aec=None
    ) -> None:
        if aec is not None:
            self._aec[session_id] = bool(aec)
        LOG.info("StackChan voice: listen %s (mode %s) for session %s", state, mode, session_id[:8])
        if state == "detect":
            self._record_uplink(0, 0.0, detect=True)
        if state in {"start", "detect"}:
            self._audio_stats[session_id] = [0, 0]
            self._followup[session_id] = (
                state == "start"
                and self._clock() - self._last_turn_end.get(session_id, float("-inf"))
                < FOLLOW_UP_AFTER_S
            )
            self._cancel_turn(session_id, send_stop=True)
            capture = StackChanAudioCapture()
            self._captures[session_id] = capture
            self._states[session_id] = "listening"
            self._modes[session_id] = mode if mode in {"auto", "manual", "realtime"} else "auto"
            self._capture_started[session_id] = self._clock()
            task = asyncio.create_task(self._run(session_id, device_id, capture))
            self._tasks[session_id] = task
        elif state == "stop":
            capture = self._captures.get(session_id)
            if capture:
                capture.close()
        elif state == "abort":
            self.abort(session_id)

    def abort(self, session_id: str) -> None:
        self._cancel_turn(session_id, send_stop=True)

    def _cancel_turn(self, session_id: str, *, send_stop: bool) -> None:
        capture = self._captures.pop(session_id, None)
        if capture:
            capture.abort()
        cancel = self._cancel_events.get(session_id)
        if cancel:
            cancel.set()
        playback = self._playbacks.get(session_id)
        flushed = bool(playback)
        if playback:
            stopped_at = self._clock()
            try:
                stop_future = playback.flush(send_stop=send_stop)
            except TypeError:
                stop_future = playback.flush()
            if send_stop and stop_future is not None:
                stop_future.add_done_callback(
                    lambda _future: setattr(
                        self, "_abort_to_silence_ms", max(0.0, (self._clock() - stopped_at) * 1000)
                    )
                )
            elif send_stop:
                self._abort_to_silence_ms = 0.0
        task = self._tasks.pop(session_id, None)
        if task:
            task.cancel()
        self._states[session_id] = "idle"
        self._speaking_since.pop(session_id, None)
        if flushed:
            # Only a real playback leaves an echo tail to ignore; stamping on every listen start
            # dropped the first 180 ms of each utterance.
            self._speech_ended[session_id] = self._clock()
        self._settled_sessions.add(session_id)
        self._emit_expression("settle")

    @property
    def latency_counters(self) -> dict[str, float | None]:
        return {
            "abort_to_silence_ms": self._abort_to_silence_ms,
            "first_audio_ms": self._first_audio_ms,
        }

    async def _recognise(self, base, cookie, capture, started_at):
        """Speech to text, listening on while the wake patience lasts.

        The hub answers a short burst with no speech (a pop-up tone, a click) as ``no_speech``. If
        the person has had less than the wake patience to speak and the device has not stopped,
        open a fresh stream on the same capture instead of ending the turn with an apology.
        """
        followup = self._followup.get(self._current_session, False)
        window = self.follow_up_s if followup else WAKE_PATIENCE_S
        deadline = started_at + window
        first = True
        while True:
            stt = self.stt_factory(base, cookie)
            self._set_live(True)
            try:
                if first and followup:
                    result = await asyncio.to_thread(stt.run, capture, patience_s=window)
                elif first:
                    result = await asyncio.to_thread(stt.run, capture)
                else:
                    remaining = max(0.5, deadline - self._clock())
                    result = await asyncio.to_thread(stt.run, capture, patience_s=remaining)
            finally:
                self._set_live(False)
            first = False
            if (
                result.kind != "no_speech"
                or getattr(capture, "closed", False)
                or self._clock() >= deadline - 0.5
            ):
                return result
            LOG.info(
                "StackChan voice: no speech yet; listening on (%.1f s of patience left)",
                deadline - self._clock(),
            )

    def _record_uplink(self, nbytes: int, peak: float, *, detect: bool = False) -> None:
        if self.uplink_stats is None:
            return
        try:
            if detect:
                self.uplink_stats.record_detect()
            else:
                self.uplink_stats.record_frame(nbytes, peak)
        except Exception:  # a counter must never break the voice path
            LOG.warning("StackChan uplink counter failed", exc_info=True)

    def _set_live(self, active: bool) -> None:
        if self.live_sink is None:
            return
        self._side.submit(self._run_live_sink, active)

    def _run_live_sink(self, active: bool) -> None:
        try:
            self.live_sink(active)
        except Exception:  # a light must never break the voice path
            LOG.warning("StackChan live cue failed", exc_info=True)

    def _emit_expression(self, state: str, *, mood: str | None = None) -> None:
        if self.expression_sink is None:
            return
        self._side.submit(self._run_expression_sink, state, mood)

    def _run_expression_sink(self, state: str, mood: str | None) -> None:
        try:
            self.expression_sink(state, mood=mood)
        except Exception:  # a failed face or head move never fails the answer
            LOG.warning("StackChan expression event failed", exc_info=True)

    def close(self) -> None:
        """Stop the side-effect worker; pending face and light updates are dropped."""
        self._side.shutdown(wait=False, cancel_futures=True)

    def _speaker_evidence(self, stt_result) -> dict | None:
        try:
            # Keep compatibility with the original zero-argument injection,
            # while allowing a provider to inspect a hub STT result.
            try:
                signature = inspect.signature(self.person_attribution)
                takes_result = bool(signature.parameters)
            except (TypeError, ValueError):
                takes_result = True
            attribution = (
                self.person_attribution(stt_result) if takes_result else self.person_attribution()
            )
        except Exception:
            LOG.warning("StackChan person attribution failed", exc_info=True)
            return None
        if not attribution:
            return None
        if isinstance(attribution, dict):
            person_id = attribution.get("person_id") or attribution.get("person")
            confidence = attribution.get("confidence")
            basis = attribution.get("basis", "voice")
            level = attribution.get("level", confidence)
        else:
            person_id = getattr(attribution, "person_id", None)
            confidence = getattr(attribution, "confidence", None)
            basis = getattr(attribution, "basis", "voice")
            level = getattr(attribution, "level", confidence)
        if not person_id:
            return None
        # The household evidence contract permits only a calibrated confirmed
        # match to establish voice identity. Keep legacy numeric providers
        # behind the documented starting threshold until they return a level.
        if level == "tentative" or level == "unknown":
            return None
        if level != "confirmed" and (not isinstance(confidence, (int, float)) or confidence < 0.6):
            return None
        if basis != "voice":
            return None
        # SPEAK-02: the one strict spec-shape builder. A numeric legacy
        # confidence that cleared the bar above is a `confirmed` match.
        if level != "confirmed":
            level = "confirmed"
        try:
            return speaker_evidence(person_id, basis, level)
        except SpeakerEvidenceError:
            LOG.warning("StackChan attribution dropped: malformed person id %r", person_id)
            return None

    async def _run(self, session_id: str, device_id: str, capture: StackChanAudioCapture) -> None:
        try:
            playback = StackChanAudioPlayback(
                self.server,
                device_id,
                clock=self._clock,
                pitch_semitones=lambda: self.pitch_semitones(),
            )
        except TypeError:
            playback = StackChanAudioPlayback(self.server, device_id)
        self._playbacks[session_id] = playback
        cancel_event = threading.Event()
        self._cancel_events[session_id] = cancel_event
        playback._cancel_event = cancel_event
        self._emit_expression("listening")
        self._settled_sessions.discard(session_id)
        started_at = self._clock()
        LOG.info("StackChan voice: turn started for session %s", session_id[:8])
        try:
            cookie = self.link.hub_client.session_cookie
            pairing = self.link.pairing_store.load()
            base = getattr(self.link.hub_client, "active_base_url", None) or (
                pairing.base_url if pairing else None
            )
            if not cookie or not base:
                LOG.warning(
                    "StackChan voice: no hub session (cookie %s, address %s); answering with the "
                    "offline line. Pair the Bot with the hub or check that the hub is reachable.",
                    "present" if cookie else "missing",
                    "present" if base else "missing",
                )
                self._emit_expression("thinking")
                await asyncio.to_thread(self._offline_line, playback)
                return
            self._current_session = session_id
            result = await self._recognise(base, cookie, capture, started_at)
            LOG.info(
                "StackChan voice: speech-to-text ended (%s, %d characters)",
                result.kind,
                len(result.text or ""),
            )
            outcome = self._classify(result)
            if outcome == "speech":
                self._breaker.note_real_final()
                self._quiet_streak = 0
            if outcome == "silence":
                # Nobody spoke (or it was not speech): end quietly and let the device go idle.
                await self._end_quietly(session_id, device_id)
                return
            self._emit_expression("thinking")
            if outcome == "failed":
                await asyncio.to_thread(self._speak_plain_error, playback, base, cookie)
                return
            if self.volume_control is not None:
                from maipai_body.bodies.stackchan.volume import confirmation, parse_volume_command

                command = parse_volume_command(result.text or "")
                if command is not None:
                    before, after = await asyncio.to_thread(self.volume_control.apply, command)
                    LOG.info(
                        "StackChan voice: volume command %s (%d -> %d)", command.kind, before, after
                    )
                    line = confirmation(command, before, after)
                    if line:
                        await asyncio.to_thread(self._say, playback, base, cookie, line)
                        self._breaker.note_speech()
                    return
            turn = self.turn_factory(base, cookie)
            chat_started = self._clock()
            events = await asyncio.to_thread(
                lambda: list(
                    turn.stream(result.text, speaker_evidence=self._speaker_evidence(result))
                )
            )
            reply = next((e.reply_text for e in reversed(events) if e.reply_text), None)
            LOG.info(
                "StackChan voice: chat ended in %.1f s (%d events, reply %d characters)",
                self._clock() - chat_started,
                len(events),
                len(reply or ""),
            )
            if reply:
                tts = self.tts_factory(base, cookie, playback)
                moods = [
                    getattr(getattr(event, "cue", None), "expressed_emotion", None)
                    for event in events
                ]
                mood = next((value for value in reversed(moods) if value), None)
                if mood:
                    self._emit_expression("reply_mood", mood=mood)
                for index, sentence in enumerate(_sentences(reply)):
                    if asyncio.current_task().cancelling():
                        return
                    self._emit_expression("speaking")
                    self._states[session_id] = "speaking"
                    self._speaking_since[session_id] = self._clock()
                    spoke_at = self._clock()
                    LOG.info(
                        "StackChan voice: text-to-speech sentence %d started (%d characters)",
                        index + 1,
                        len(sentence),
                    )
                    await asyncio.to_thread(tts.speak, sentence, stop_event=cancel_event)
                    synthesized_at = self._clock()
                    if cancel_event.is_set():
                        return
                    # stop() sends the audio and waits on this event loop's own coroutine, so it
                    # must run off the loop: inline it deadlocked until its 30 s timeout.
                    await asyncio.to_thread(playback.stop)
                    LOG.info(
                        "StackChan voice: sentence %d synthesized in %.1f s, sent to the "
                        "device in %.1f s",
                        index + 1,
                        synthesized_at - spoke_at,
                        self._clock() - synthesized_at,
                    )
                    self._states[session_id] = "listening"
                    self._speech_ended[session_id] = self._clock()
                await asyncio.to_thread(playback.end)
                self._breaker.note_speech()
                LOG.info("StackChan voice: reply finished playing")
            else:
                await asyncio.to_thread(self._speak_plain_error, playback, base, cookie)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("StackChan voice turn failed: %s: %s", type(exc).__name__, str(exc)[:160])
            LOG.debug("StackChan voice turn failure detail", exc_info=True)
            if isinstance(exc, (TurnAuthFailed, TurnLinkLost, TtsAuthFailed)):
                await asyncio.to_thread(self._offline_line, playback)
            else:
                await asyncio.to_thread(self._speak_plain_error, playback, base, cookie)
        finally:
            if self._states.get(session_id) == "speaking":
                # A reply that ended abnormally must not leave the mouth open.
                try:
                    await self.server.stop_audio(device_id)
                except Exception:
                    LOG.debug(
                        "StackChan voice: tts stop after an abnormal end failed", exc_info=True
                    )
            self._last_turn_end[session_id] = self._clock()
            if session_id not in self._settled_sessions:
                self._emit_expression("settle")
            self._states[session_id] = "idle"
            self._settled_sessions.discard(session_id)
            self._captures.pop(session_id, None)
            self._tasks.pop(session_id, None)
            self._playbacks.pop(session_id, None)
            self._cancel_events.pop(session_id, None)
            frames, size = self._audio_stats.pop(session_id, [0, 0])
            LOG.info(
                "StackChan voice: turn ended after %.1f s (%d audio frames, %d bytes)",
                self._clock() - started_at,
                frames,
                size,
            )

    def _offline_line(self, playback) -> None:
        if not self._breaker.allow():  # a canned error line: same loop breaker as the apology
            return
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

    def _classify(self, result) -> str:
        """``silence`` (end quietly), ``failed`` (apologise once) or ``speech`` (go on)."""
        text = (result.text or "").strip()
        if result.kind in {"no_speech", "timeout"}:
            return "silence"
        if result.kind == "final":
            return "speech" if text else "silence"
        # kind == "error": only an apology if the hub really heard someone speak.
        return "failed" if (result.speech_s or 0.0) >= MIN_SPEECH_S else "silence"

    async def _end_quietly(self, session_id: str, device_id: str) -> None:
        self._quiet_streak += 1
        LOG.info(
            "StackChan voice: no speech to answer (%d quiet turn%s in a row); going idle%s",
            self._quiet_streak,
            "" if self._quiet_streak == 1 else "s",
            " and waiting for the wake word" if self._quiet_streak >= 2 else "",
        )
        send_idle = getattr(self.server, "send_idle", None)
        if callable(send_idle):
            try:
                await send_idle(device_id)
            except Exception:
                LOG.debug("StackChan voice: idle request failed", exc_info=True)

    def _say(self, playback, base: str, cookie: str, text: str) -> None:
        """Speak one short line through the hub's voice (a confirmation, not a chat reply)."""
        try:
            self.tts_factory(base, cookie, playback).speak(text)
            playback.stop()
            playback.end()
        except Exception:
            LOG.warning("StackChan voice: could not speak %r", text, exc_info=True)

    def _speak_plain_error(self, playback, base: str, cookie: str) -> None:
        if not self._breaker.allow():
            return
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
