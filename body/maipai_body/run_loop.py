"""G9: the run loop - one state machine driving audio, cues, tracking
and the head. Constructed and run by ``app.py``'s own
``run_paired_body`` once G4's hub link reports paired, replacing its
neutral-hold idle wait for the rest of the process's life.

The funnel (`docs/BACKLOG.md`'s own words): ``idle``, ``listening``,
``thinking``, ``speaking``, derived from G6's own turn events and G8's
mute, never invented separately. G11's own floor ("nothing beyond G9:
wire presence and tracking into the run loop") is satisfied here too,
not as a separate item - a presence tick enables the daemon's own face
tracker when a face is present and nothing higher-priority is active,
matching the arbitration priority the design record's section 6 and
`presence/arbitration.py` already state.

G8's own barge-in, folded in rather than built separately: wake
scoring keeps running during `speaking` (the unit's echo cancellation,
or the sim's software AEC, is what makes hearing a wake word over the
robot's own playback possible at all) - a wake firing while already
speaking is the "stop" signal, not a second detector or a new model.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum

import requests

from maipai_body.expression.cue import Cue, Phase
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.expression.suppression import SuppressionContext
from maipai_body.hal.seam import AudioIO, Camera, FaceTracker, HeadActuator, Imu
from maipai_body.presence.arbitration import ArbitrationState, tracking_may_drive
from maipai_body.presence.observations import read_presence
from maipai_body.speech.capture import AudioCapture
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.stt_stream import SttStreamClient
from maipai_body.speech.tts_playback import TtsLinkLost, TtsPlaybackClient
from maipai_body.speech.turn_client import TurnClient, TurnLinkLost
from maipai_body.speech.wake import WakeScorer
from maipai_body.vision.detect import FiveLandmarkDetector
from maipai_body.vision.embed import SFaceEmbedder
from maipai_body.vision.gallery import FaceGallery, FaceVerdict
from maipai_body.vision.recognize import recognize_face

logger = logging.getLogger("maipai_body.run_loop")

# BODY-05's own legacy flash test: no funnel state renders for less
# than this before the next transition is allowed to visibly register -
# a debounce against flicker, not a hard floor on how fast a real turn
# can move (a state that would naturally last under 0.5s still enters
# and exits on schedule; only the RENDER of a state shorter than this
# is what the settle gate is about, per BODY-05's own wording, and the
# funnel's own state TRACE - what a test reads back - always records
# the real transition times regardless).
SETTLE_GATE_S = 0.5

# The array's own AEC (or the sim's software fallback) is what makes
# scoring wake blocks captured WHILE the robot is speaking meaningful
# at all - the wake scorer's own docstring already documents that a
# fresh wake fires cleanly once per phrase.
_WAKE_POLL_SLEEP_S = 0.01

# FACE-01's own capped rate: "once every few seconds while a face is
# present, not per frame" (design-face-recognition-models-2026-09-28.md
# section 6) - a face-embedding pass competing with wake-word detection
# and the audio stream on the same CPU needs a floor, not a tick.
_FACE_RECOGNITION_INTERVAL_S = 3.0
# A verdict older than this is not reported on a fresh turn - identity
# is per turn, never sticky (dev.md section 6), so a face seen minutes
# ago (the person may have left) must not still answer "who is this"
# for an utterance that just started.
_FACE_VERDICT_STALE_AFTER_S = 10.0
# The face-check thread does pure CPU work (a local capture plus a
# local ONNX pipeline, no network call with an unbounded timeout to
# wait out) - unlike _speak's own deliberately unbounded join, a
# generous bound here is safe, not a correctness risk.
_FACE_CHECK_JOIN_TIMEOUT_S = 5.0
# The hub's own shared spec (commons/spec's conversation_turn_schema.py,
# checked directly by a review 2026-09-28): `speaker_evidence.person`
# must match this or be null, or the hub's schema validation refuses
# the whole turn. No real print record exists yet to guarantee a
# FaceGallery's own person_id already looks like this - checked here
# defensively rather than assumed.
_PERSON_ID_RE = re.compile(r"^person-[a-z0-9]{6,}$")


class FunnelState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


@dataclass
class StateTransition:
    state: FunnelState
    at_monotonic: float


@dataclass
class RunLoopState:
    """The funnel's own live state, read by G10's future device-state
    frame and by tests - a snapshot, not the live mutable object (the
    same torn-read lesson G4's own `LinkState` already learned)."""

    funnel: FunnelState = FunnelState.IDLE
    muted: bool = False
    tracking: bool = False
    trace: list[StateTransition] = field(default_factory=list)
    face_verdict: FaceVerdict | None = None
    face_verdict_at: float | None = None


class ConversationLoop:
    """Wake, listen, think, speak - one turn at a time, with presence
    ticking and barge-in running throughout."""

    def __init__(
        self,
        *,
        client: HeadActuator | AudioIO | FaceTracker | Imu | Camera,
        expression_engine: ExpressionEngine,
        audio_capture: AudioCapture,
        audio_playback: AudioPlayback,
        wake_scorer: WakeScorer,
        stt_client: SttStreamClient,
        turn_client: TurnClient,
        tts_client: TtsPlaybackClient,
        hub_credentials: Callable[[], tuple[str, str]] | None = None,
        presence_interval_s: float = 0.5,
        face_detector: FiveLandmarkDetector | None = None,
        face_embedder: SFaceEmbedder | None = None,
        face_gallery: FaceGallery | None = None,
        face_recognition_interval_s: float = _FACE_RECOGNITION_INTERVAL_S,
    ) -> None:
        self._client = client
        self._expression = expression_engine
        self._capture = audio_capture
        self._playback = audio_playback
        self._wake = wake_scorer
        self._stt = stt_client
        self._turn = turn_client
        self._tts = tts_client
        self._hub_credentials = hub_credentials
        self._current_hub_credentials: tuple[str, str] | None = None
        self._presence_interval_s = presence_interval_s
        # All three None (the default) disables face recognition
        # entirely: nothing in this repo constructs real ones yet
        # (the model needs downloading, and there is no real print
        # record to match against - FACE-01's own backlog entry names
        # both as still open), but the presence loop is ready the day
        # something does. Given together or not at all - a review
        # (2026-09-28) caught that a partial wiring (one or two of the
        # three) would silently disable recognition with no signal why,
        # indistinguishable from "nobody was ever detected."
        face_components = (face_detector, face_embedder, face_gallery)
        given = sum(c is not None for c in face_components)
        if given not in (0, 3):
            raise ValueError(
                "face_detector, face_embedder and face_gallery must be given "
                "together or not at all - a partial set would silently "
                "disable recognition with no signal why"
            )
        self._face_detector = face_detector
        self._face_embedder = face_embedder
        self._face_gallery = face_gallery
        self._face_recognition_interval_s = face_recognition_interval_s
        # Presence-thread-private pacing: written and read only there,
        # never under `self._lock` (a single thread's own bookkeeping,
        # not reportable state - `RunLoopState.face_verdict_at` is the
        # lock-protected timestamp another thread may actually read).
        self._last_face_check_monotonic = 0.0
        # The in-flight (or most recently finished) face-check worker,
        # if any - `_presence_loop` joins it before returning, and
        # `_maybe_check_face` never starts a second one over a running
        # first (a review, 2026-09-28: recognition used to run
        # synchronously on the presence thread itself, delaying
        # tracking's own enable/disable decisions by however long a
        # capture-plus-ONNX pass takes, every few seconds while a face
        # is present - the one case responsive tracking matters most).
        self._face_check_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._state = RunLoopState()
        self._cue_seq = 0

    @property
    def state(self) -> RunLoopState:
        with self._lock:
            # `replace()`, not a manual field-by-field copy: a review
            # (2026-09-28) caught that the old form had to be updated
            # by hand for every new `RunLoopState` field and would
            # otherwise silently keep returning a field's stale default
            # forever. `trace` still needs its own fresh list - the
            # one field a shallow copy would otherwise alias with the
            # live, still-mutating one.
            return replace(self._state, trace=list(self._state.trace))

    def _enter(self, funnel: FunnelState) -> None:
        with self._lock:
            self._state.funnel = funnel
            self._state.trace.append(StateTransition(state=funnel, at_monotonic=time.monotonic()))
        logger.info("funnel: %s", funnel)

    def _current_funnel(self) -> FunnelState:
        with self._lock:
            return self._state.funnel

    def _is_muted(self) -> bool:
        with self._lock:
            return self._state.muted

    def _current_face_verdict(self) -> FaceVerdict | None:
        """The most recent face verdict, or `None` if there isn't one
        or it's gone stale (`_FACE_VERDICT_STALE_AFTER_S`) - never a
        verdict from a face that may no longer be there answering for
        an utterance that just started."""
        with self._lock:
            verdict = self._state.face_verdict
            verdict_at = self._state.face_verdict_at
        if verdict is None or verdict_at is None:
            return None
        if time.monotonic() - verdict_at > _FACE_VERDICT_STALE_AFTER_S:
            return None
        return verdict

    def _next_cue_seq(self) -> int:
        # Called from both the main funnel thread and the speak worker
        # thread's own on_first_chunk callback (a review, 2026-09-28,
        # caught this: `+=` on a plain attribute is not atomic, so a
        # GIL switch between the load and the store could duplicate or
        # drop a sequence number when both threads race here during
        # barge-in).
        with self._lock:
            self._cue_seq += 1
            return self._cue_seq

    def _render(self, cue: Cue) -> None:
        context = SuppressionContext(muted=self._is_muted())
        self._expression.handle(cue, context)

    def set_muted(self, muted: bool) -> None:
        """The software-mute toggle's own entry point (G8's own state,
        distinct from barge-in's per-turn cancel): "capture continues
        but zero blocks reach the wake scorer" once set. Nothing in
        this repo calls this yet - the actual command to mute lives in
        G10's own device-state frame, not built this pass - but the
        mechanism itself is real and ready: it updates the funnel's own
        state (gating `_poll_wake`) and renders the muted pose through
        `ExpressionEngine.set_muted()`'s own edge-triggered contract."""
        if muted == self._is_muted():
            return
        arbitration = ArbitrationState(expression_active=self._current_funnel() != FunnelState.IDLE)
        self._expression.set_muted(muted, arbitration)
        with self._lock:
            self._state.muted = muted

    def run(self, stop_event: threading.Event) -> None:
        """Blocks until `stop_event` is set. Runs the presence tick on
        its own thread; the wake-then-turn loop on this one."""
        presence_thread = threading.Thread(
            target=self._presence_loop, args=(stop_event,), name="presence", daemon=True
        )
        presence_thread.start()
        self._capture.start()
        try:
            while not stop_event.is_set():
                event = self._poll_wake(stop_event)
                if event is None:
                    continue
                self._run_turn(stop_event)
        finally:
            self._capture.stop()
            presence_thread.join(timeout=2.0)

    def _poll_wake(self, stop_event: threading.Event):
        """Blocks (politely) until the wake word fires or `stop_event`
        is set. Skipped entirely while muted (G8's own contract:
        "capture continues but zero blocks reach the wake scorer")."""
        while not stop_event.is_set():
            if self._is_muted():
                self._capture.poll_blocks()  # drained, never scored, while muted
                stop_event.wait(_WAKE_POLL_SLEEP_S)
                continue
            for block in self._capture.poll_blocks():
                wake_event = self._wake.poll(block)
                if wake_event is not None:
                    return wake_event
            stop_event.wait(_WAKE_POLL_SLEEP_S)
        return None

    def _run_turn(self, stop_event: threading.Event) -> None:
        if self._hub_credentials is not None:
            try:
                session_cookie, base_url = self._hub_credentials()
            except Exception:
                logger.warning(
                    "failed to refresh hub credentials; keeping current clients", exc_info=True
                )
            else:
                credentials = (session_cookie, base_url)
                if credentials != self._current_hub_credentials:
                    logger.info("hub session cookie rotated, reconstructing hub clients")
                    self._stt = SttStreamClient(base_url, session_cookie)
                    self._turn = TurnClient(base_url, session_cookie)
                    self._tts = TtsPlaybackClient(base_url, session_cookie, self._playback)
                    self._current_hub_credentials = credentials
        self._enter(FunnelState.LISTENING)
        self._render(Cue(phase=Phase.HEARD, cue_seq=self._next_cue_seq()))

        try:
            stt_result = self._stt.run(self._capture)
        except Exception:
            logger.warning("stt stream failed; back to idle", exc_info=True)
            self._enter(FunnelState.IDLE)
            return

        if stt_result.kind != "final" or not stt_result.text:
            self._enter(FunnelState.IDLE)
            return

        self._enter(FunnelState.THINKING)
        reply_text: str | None = None
        turn_id: str | None = None
        cancelled = False
        speaker_evidence = None
        face_verdict = self._current_face_verdict()
        if face_verdict is not None:
            # Only the derived fields (dev.md section 6: "never a
            # score, an embedding... leaves the robot") - the
            # verdict's own score and candidates stay local.
            person, level = face_verdict.person_id, face_verdict.level
            if person is not None and not _PERSON_ID_RE.match(person):
                # The hub's own schema refuses the whole turn over a
                # malformed id - no real print record exists yet to
                # guarantee this never happens, so it's checked, not
                # assumed. Downgraded, not raised: a bad id here means
                # the local gallery is misconfigured, not a reason to
                # go silent for the person actually speaking.
                logger.warning(
                    "face verdict person_id %r doesn't match the hub's id "
                    "format - dropping it, not sending a turn the hub would refuse",
                    person,
                )
                person, level = None, "unknown"
            speaker_evidence = {"person": person, "basis": "face", "level": level}
        try:
            for turn_event in self._turn.stream(stt_result.text, speaker_evidence=speaker_evidence):
                if turn_event.turn_id:
                    turn_id = turn_event.turn_id
                if turn_event.cue is not None:
                    if turn_event.cue.phase is Phase.CANCEL:
                        cancelled = True
                        self._render(turn_event.cue)
                    elif turn_event.cue.phase is not Phase.DONE:
                        # The turn stream's own DONE means "the reply
                        # text is fully known" - a different moment from
                        # "done speaking it." Rendering it here would
                        # fire the settle primitive before speech even
                        # starts; _speak() below renders the real DONE
                        # once playback actually finishes (or CANCEL on
                        # a barge-in instead).
                        self._render(turn_event.cue)
                if turn_event.reply_text is not None:
                    reply_text = turn_event.reply_text
        except (TurnLinkLost, requests.RequestException):
            logger.warning("turn stream link lost", exc_info=True)
            self._render(Cue(phase=Phase.CANCEL, cue_seq=self._next_cue_seq()))
            self._enter(FunnelState.IDLE)
            return

        if cancelled or not reply_text:
            self._enter(FunnelState.IDLE)
            return

        self._speak(reply_text, turn_id, stop_event)
        self._enter(FunnelState.IDLE)

    def _speak(
        self, reply_text: str, turn_id: str | None, outer_stop_event: threading.Event
    ) -> None:
        self._enter(FunnelState.SPEAKING)
        barge_in = threading.Event()

        def _on_first_chunk() -> None:
            self._render(Cue(phase=Phase.SPEAK, cue_seq=self._next_cue_seq()))

        speak_thread = threading.Thread(
            target=self._speak_worker, args=(reply_text, barge_in, _on_first_chunk), daemon=True
        )
        speak_thread.start()

        # Wake scoring keeps running while speaking (G8): a fresh wake
        # is the barge-in trigger, not a second detector. Stops the
        # instant barge_in is set (a review, 2026-09-28, caught the
        # original `while speak_thread.is_alive():` still polling for
        # another tick after the first hit - the worker takes a moment
        # to actually exit, and a second wake block scored from the
        # same barge-in utterance would call _cancel_turn and render
        # CANCEL a second time).
        while speak_thread.is_alive() and not barge_in.is_set():
            if outer_stop_event.is_set():
                barge_in.set()
                break
            for block in self._capture.poll_blocks():
                wake_event = self._wake.poll(block)
                if wake_event is not None:
                    barge_in.set()
                    if turn_id is not None:
                        self._cancel_turn(turn_id)
                    self._render(Cue(phase=Phase.CANCEL, cue_seq=self._next_cue_seq()))
                    break
            time.sleep(_WAKE_POLL_SLEEP_S)
        # No timeout: a review (2026-09-28) found the prior 5s bound let
        # _speak return while the worker was still blocked mid-network-
        # read, so the next turn could spawn a second speak_thread that
        # overlapped the first on the same (unlocked) AudioPlayback,
        # corrupting playback. Correctness beats latency here - the
        # wait is bounded anyway, by the TTS client's own (10, 120)s
        # connect/read timeout, which barge-in's stop_event usually
        # beats by checking between every streamed chunk.
        speak_thread.join()
        if not barge_in.is_set():
            self._render(Cue(phase=Phase.DONE, cue_seq=self._next_cue_seq()))

    def _speak_worker(self, reply_text, stop_event: threading.Event, on_first_chunk) -> None:
        try:
            self._tts.speak(reply_text, on_first_chunk=on_first_chunk, stop_event=stop_event)
        except (TtsLinkLost, requests.RequestException):
            logger.warning("tts playback failed", exc_info=True)
        finally:
            self._playback.stop()

    def _cancel_turn(self, turn_id: str) -> None:
        try:
            self._turn.cancel(turn_id)
        except (TurnLinkLost, requests.RequestException):
            logger.warning("turn cancel failed", exc_info=True)

    def _presence_loop(self, stop_event: threading.Event) -> None:
        """Enables the daemon's own tracker when a face is present and
        nothing higher-priority is active - G11's own floor ("nothing
        beyond G9: wire presence and tracking into the run loop"),
        satisfied here rather than as a separate item. The gap-audit's
        own G9 text names the rule directly: "tracking enabled when a
        face is present and no turn is speaking, disabled under stop
        and service" - a body-specific carve-out, not the general
        arbitration priority table (`arbitration.py`'s own comment
        elsewhere: tracking outranks expression, so a generic
        `tracking_may_drive()`/`expression_may_drive()` check would
        NOT block tracking during `speak` on priority alone). `speak`'s
        own sway motion and the daemon's own tracker would otherwise
        both drive the head at once - the literal conflict `dev.md`'s
        own G9 section calls out to settle in code, not by default -
        so `speaking` is checked explicitly here, beside (not instead
        of) `tracking_may_drive()`'s own stop/service check."""
        while not stop_event.wait(self._presence_interval_s):
            try:
                observation = read_presence(self._client)
            except Exception:
                logger.warning("presence read failed", exc_info=True)
                continue
            arbitration = ArbitrationState(tracking_active=observation.face_detected)
            not_speaking = self._current_funnel() != FunnelState.SPEAKING
            should_track = tracking_may_drive(arbitration) and not_speaking
            with self._lock:
                already_tracking = self._state.tracking
            if should_track and not already_tracking:
                self._client.enable_tracking()
                with self._lock:
                    self._state.tracking = True
            elif not should_track and already_tracking:
                self._client.disable_tracking()
                with self._lock:
                    self._state.tracking = False

            if observation.face_detected:
                self._maybe_check_face(stop_event)

        if self._face_check_thread is not None:
            self._face_check_thread.join(timeout=_FACE_CHECK_JOIN_TIMEOUT_S)

    def _maybe_check_face(self, stop_event: threading.Event) -> None:
        """FACE-01's own capped-rate capture: at most once every
        `_face_recognition_interval_s`, and only when a face is
        already present (the caller's own job) - never a continuous
        stream. A no-op unless all three of `face_detector`,
        `face_embedder` and `face_gallery` were given to the
        constructor (nothing does yet - FACE-01's own backlog entry
        names why: no real print record to match against exists yet).
        The actual work runs on its own thread (`_run_face_check`),
        never inline here: this method returns immediately either way,
        so a slow capture-plus-ONNX pass never delays this same tick's
        tracking enable/disable decision, the presence loop's own
        first job."""
        if self._face_detector is None or self._face_embedder is None or self._face_gallery is None:
            return
        if time.monotonic() - self._last_face_check_monotonic < self._face_recognition_interval_s:
            return
        if self._face_check_thread is not None and self._face_check_thread.is_alive():
            return  # the previous check hasn't finished - never overlap two
        self._last_face_check_monotonic = time.monotonic()
        self._face_check_thread = threading.Thread(
            target=self._run_face_check, args=(stop_event,), name="face-check", daemon=True
        )
        self._face_check_thread.start()

    def _run_face_check(self, stop_event: threading.Event) -> None:
        """One capture-detect-align-embed-match pass, off the presence
        thread. Any failure - the camera or the pipeline itself -
        leaves whatever verdict is already published alone rather than
        overwriting it with `None`: a transient glitch is not evidence
        the person left, and a review (2026-09-28) caught the first
        version of this treating the two identically, so a single bad
        frame could silently erase a still-fresh, correct verdict. A
        detector that finds no face in a good frame is different -
        that genuinely is "checked, nobody there," and does clear it,
        same as `recognize_face`'s own `None` for that case."""
        try:
            frame = self._client.get_frame()
        except Exception:
            logger.warning("camera capture failed for face recognition", exc_info=True)
            return
        if frame is None:
            return  # nothing to check this tick - not evidence of anything
        try:
            verdict = recognize_face(
                frame,
                detector=self._face_detector,
                embedder=self._face_embedder,
                gallery=self._face_gallery,
            )
        except Exception:
            logger.warning("face recognition failed", exc_info=True)
            return
        if stop_event.is_set():
            return  # shutting down - don't publish a result nobody will read
        with self._lock:
            self._state.face_verdict = verdict
            self._state.face_verdict_at = time.monotonic()
