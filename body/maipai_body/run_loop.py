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
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field, replace

import requests

from maipai_body.expression.cue import Cue, Phase
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.expression.suppression import SuppressionContext
from maipai_body.hal.seam import AudioIO, Camera, FaceTracker, HeadActuator, Imu
from maipai_body.link.commands import LocalCommand, Reply, route_phrase
from maipai_body.link.offline import OfflineRungs
from maipai_body.link.replay import ReplayItem
from maipai_body.link.state_machine import LinkPhase
from maipai_body.presence.arbitration import ArbitrationState, tracking_may_drive
from maipai_body.presence.carry_reaction import (
    CARRY_LINES,
    DEFAULT_CARRY_REACTION,
    CarryReaction,
    PresenceEntry,
    line_allowed,
)
from maipai_body.presence.funnel import FunnelState, FunnelView, SettleGate
from maipai_body.presence.motion_state import MotionState, MotionStateMachine
from maipai_body.presence.observations import read_presence
from maipai_body.speech.capture import AudioCapture
from maipai_body.speech.offline_clips import FREEFALL as FREEFALL_CLIP
from maipai_body.speech.offline_clips import RECONNECT as RECONNECT_CLIP
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

# BODY-05's legacy flash test: the state SHOWN to readers (the eyes, the
# mouth, the ring, the screen, the link) never changes sooner than this
# after the previous shown change, so a 45 ms flash is held open to a full
# half second instead. The loop itself acts on the raw state at once
# (barge-in, tracking and the line rules must not lag); `RunLoopState.trace`
# records the raw transitions, `shown_trace` what readers were given.
SETTLE_GATE_S = 0.5

# The array's own AEC (or the sim's software fallback) is what makes
# scoring wake blocks captured WHILE the robot is speaking meaningful
# at all - the wake scorer's own docstring already documents that a
# fresh wake fires cleanly once per phrase.
_WAKE_POLL_SLEEP_S = 0.01
# The body's acknowledgement of a wake the hub cannot take (the same primitive
# rung 0 uses as its stir): the user always sees that the wake was heard.
_WAKE_ACK_PRIMITIVE = "perk"

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

# M-R5 / design record section 4: when a turn was lost to the link, the
# robot says one line once the hub answers again, never one per failed
# turn. Spoken as the head of the next reply that reaches the hub: until
# G4b's pre-rendered offline clips exist the hub's own `tts` route is the
# only voice this body has, so the first moment it can speak at all is the
# first moment the hub answers. G4b's reconnect clip replaces this text
# whenever the bundle can say it; this stays the fallback without one.
# The wording is a first cut for the owner's call (the design record names
# the unreachable line, "I can't reach home right now", not this one).
LINK_RESTORED_LINE = "Sorry, I lost my connection to home for a moment."


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
    # What readers are shown: `funnel` after the settle gate (BODY-05).
    shown: FunnelState = FunnelState.IDLE
    muted: bool = False
    held: bool = False
    alarm: bool = False
    tracking: bool = False
    trace: list[StateTransition] = field(default_factory=list)
    shown_trace: list[StateTransition] = field(default_factory=list)
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
        on_change: Callable[[], None] | None = None,
        presence_interval_s: float = 0.5,
        face_detector: FiveLandmarkDetector | None = None,
        face_embedder: SFaceEmbedder | None = None,
        face_gallery: FaceGallery | None = None,
        face_recognition_interval_s: float = _FACE_RECOGNITION_INTERVAL_S,
        offline: OfflineRungs | None = None,
        react_hook: Callable[..., bool] | None = None,
        motion_clock: Callable[[], float] = time.monotonic,
        carry_gravity_compensation: bool = False,
        teach_active: Callable[[], bool] | None = None,
        carry_reaction: Callable[[], CarryReaction] | None = None,
        presence_entries: Callable[[], Sequence[PresenceEntry] | None] | None = None,
        settle_gate_s: float = SETTLE_GATE_S,
        funnel_clock: Callable[[], float] = time.monotonic,
        capture_scope: Callable[[], AbstractContextManager[object]] | None = None,
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
        self._on_change = on_change
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
        # BODY-05: a filter over the one funnel, never a second machine. The
        # timer lands a held change; every use is under `self._lock`.
        self._funnel_clock = funnel_clock
        self._settle = SettleGate(settle_gate_s, initial=FunnelState.IDLE)
        self._settle_timer: threading.Timer | None = None
        self._view_subscribers: list[Callable[[FunnelView], None]] = []
        # EYES-02: wraps the one stretch where the voice leaves for the hub (the
        # STT stream), so the live cue is true to what is sent; local wake
        # scoring and rung 1 stay outside it.
        self._capture_scope = capture_scope or nullcontext
        self._cue_seq = 0
        # A turn was lost to the link and the line about it is still
        # owed. A plain bool, not a count: several lost turns in one
        # outage are announced once. Only the funnel thread reads or
        # writes it (the speak worker reports through an Event).
        self._lost_turn_unannounced = False
        # The presence thread's edge detector for the freefall line.
        self._freefall_active = False
        # LINK-STATE-01: the offline ladder. None keeps the loop exactly as
        # it was; with one, a lost link feeds the machine, an outage answers
        # wakes with rung 1 only, and the machine's edges are state changes.
        self._offline = offline
        # MOVES-01 plan react hook; optional and inert until the wire names a move.
        self._react_hook = react_hook
        # MOVE-CARRY-01: lifted, carried and put down. `holding` is the motion
        # floor: no tracking, cue, breathe or move is commanded while it is true.
        self._motion = MotionStateMachine()
        self._motion_state = MotionState.RESTING
        self._motion_clock = motion_clock
        # UNVERIFIED and off by default (the profile's carry_gravity_compensation);
        # never toggled while a MOVES-02 teach session holds it.
        self._carry_gravity_compensation = carry_gravity_compensation
        self._teach_active = teach_active or (lambda: False)
        self._gravity_on_by_us = False
        # MOVE-CARRY-01c: `robot.motion.carry_reaction` (look unless set) governs only
        # the look and the line. The age bands of everyone present come from
        # `presence_entries`; None, or an answer of None, means no presence
        # information and gives the silent look.
        self._carry_reaction = carry_reaction or (lambda: DEFAULT_CARRY_REACTION)
        self._presence_entries = presence_entries
        self._carry_line_index = 0
        if offline is not None:
            offline.machine.subscribe(lambda _old, _new: self._notify_change())
            if offline.rung0 is not None:
                offline.rung0.attach(
                    render=self._render_ambient,
                    may_drive=self._body_is_free,
                    on_reconnect_spoken=self._reconnect_spoken,
                )

    def _notify_change(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def _render_ambient(self, primitive: str) -> bool:
        """Rung 0's way onto the body: a state-driven primitive through the
        same engine, suppression table and lock the turn cues use."""
        return self._expression.render_ambient(primitive, self._suppression_context()).rendered

    def _suppression_context(self) -> SuppressionContext:
        return SuppressionContext(muted=self._is_muted(), held=self._motion.holding)

    @property
    def motion_state(self) -> MotionState:
        """The latest motion state; tip and freefall outrank the held states."""
        return self._motion_state

    def _body_is_free(self) -> bool:
        """Rung 0 may move the head only when no turn and no tracker owns it."""
        with self._lock:
            return self._state.funnel == FunnelState.IDLE and not self._state.tracking

    def _reconnect_spoken(self) -> None:
        """The reconnect clip said the one line, so the hub's own wording of
        it (``LINK_RESTORED_LINE``) is no longer owed."""
        self._lost_turn_unannounced = False

    def _in_outage(self) -> bool:
        return self._offline is not None and self._offline.machine.phase is not LinkPhase.CONNECTED

    def _tracking_allowed(self) -> bool:
        offline = self._offline
        if offline is None or offline.rung0 is None:
            return True
        return offline.rung0.tracking_allowed()

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
            return replace(
                self._state,
                trace=list(self._state.trace),
                shown_trace=list(self._state.shown_trace),
            )

    def subscribe_view(self, callback: Callable[[FunnelView], None]) -> None:
        """Tell ``callback`` the funnel's ``FunnelView`` whenever the SHOWN state,
        the mute, the held state or the alarm changes, on whichever thread made
        the change. This and ``view()`` are the readers' whole view of the
        funnel (the eyes' director reads nothing else of the loop)."""
        with self._lock:
            self._view_subscribers.append(callback)

    def view(self) -> FunnelView:
        with self._lock:
            return self._view_locked()

    def _view_locked(self) -> FunnelView:
        state = self._state
        return FunnelView(shown=state.shown, muted=state.muted, held=state.held, alarm=state.alarm)

    def _emit_view(self) -> None:
        with self._lock:
            view = self._view_locked()
            subscribers = list(self._view_subscribers)
        for callback in subscribers:
            try:
                callback(view)
            except Exception:
                logger.warning("funnel subscriber failed", exc_info=True)

    def _enter(self, funnel: FunnelState) -> None:
        now = self._funnel_clock()
        with self._lock:
            self._state.funnel = funnel
            self._state.trace.append(StateTransition(state=funnel, at_monotonic=now))
            shown_changed = self._settle.offer(funnel, now)
            if shown_changed:
                self._record_shown_locked(now)
            self._arm_settle_timer_locked(now)
        logger.info("funnel: %s", funnel)
        if shown_changed:
            self._emit_view()
        if self._on_change is not None:
            self._on_change()

    def _record_shown_locked(self, now: float) -> None:
        shown = self._settle.shown
        self._state.shown = shown
        self._state.shown_trace.append(StateTransition(state=shown, at_monotonic=now))

    def _arm_settle_timer_locked(self, now: float) -> None:
        if self._settle_timer is not None:
            self._settle_timer.cancel()
            self._settle_timer = None
        due = self._settle.due_in(now)
        if due is None:
            return
        timer = threading.Timer(due, self._land_held_state)
        timer.daemon = True
        self._settle_timer = timer
        timer.start()

    def _land_held_state(self) -> None:
        now = self._funnel_clock()
        with self._lock:
            landed = self._settle.flush(now)
            if landed:
                self._record_shown_locked(now)
            self._arm_settle_timer_locked(now)
        if landed:
            self._emit_view()
            if self._on_change is not None:
                self._on_change()

    def _cancel_settle_timer(self) -> None:
        with self._lock:
            if self._settle_timer is not None:
                self._settle_timer.cancel()
                self._settle_timer = None

    def snapshot(self) -> dict[str, object]:
        """Return the reportable funnel state without exposing live state."""
        with self._lock:
            activity = self._state.shown.value
            idle = self._state.shown == FunnelState.IDLE
        if idle and self._offline is not None:
            phase = self._offline.machine.phase
            if phase is not LinkPhase.CONNECTED:
                activity = phase.value  # `reconnecting` or `sleeping` (spec-v0.1.73)
        with self._lock:
            return {
                "activity": activity,
                "muted": self._state.muted,
                "tracking": self._state.tracking,
            }

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
        self._expression.handle(cue, self._suppression_context())

    def _link_lost(self, reason: str = "the hub stopped answering") -> None:
        """Section 7: loss of the hub mid-turn is `cancel`, `link_lost`.
        Renders it once (the stop primitive holds the pose, so the head
        settles where it is) and owes the one line on reconnect. With the
        offline ladder it also tells the machine, which starts the walk."""
        self._render(Cue(phase=Phase.CANCEL, cue_seq=self._next_cue_seq()))
        self._lost_turn_unannounced = True
        if self._offline is not None:
            self._offline.machine.link_lost(reason)

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
        self._emit_view()
        if self._on_change is not None:
            self._on_change()

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
                if self._in_outage() and not self._retry_link():
                    self._run_offline_command(stop_event)
                else:
                    self._run_turn(stop_event)
        finally:
            self._cancel_settle_timer()
            self._capture.stop()
            presence_thread.join(timeout=2.0)
            close_expression = getattr(self._expression, "close", None)
            if close_expression is not None:
                close_expression()

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

    def _retry_link(self) -> bool:
        """A wake during an outage first walks the addresses once, at once,
        so a hub that already came back is used with no dead time. True
        means the link is up and the wake runs as a normal turn."""
        offline = self._offline
        if offline is not None and offline.retry_link is not None:
            try:
                offline.retry_link()
            except Exception:
                logger.warning("wake-time address walk failed", exc_info=True)
        return not self._in_outage()

    def _run_offline_command(self, stop_event: threading.Event) -> None:
        """Rung 1: a wake during an outage listens for one of the closed
        list of local commands and nothing else. No STT stream, no turn, no
        queue: a phrase off the list is dropped (the gate only counts the
        refusal) and the funnel never leaves `idle` for it. A command
        shows `speaking` for its fixed reply and goes back to `idle`.
        A wake is never silent: the acknowledgement animation always plays,
        and with no keyword spotter wired the rung 2 status line is the reply."""
        offline = self._offline
        assert offline is not None
        self._render_ambient(_WAKE_ACK_PRIMITIVE)
        if offline.recognizer is None or offline.router is None:
            # No keyword spotter wired (its CPU cost is UNVERIFIED).
            status = offline.status()
            speaker = offline.speaker
            selected = (
                speaker.selected_variant(status.clip_ids[0])
                if speaker is not None and status.clip_ids and hasattr(speaker, "selected_variant")
                else None
            )
            reply = Reply(
                selected[1] if selected else status.text,
                (selected[0],) if selected else status.clip_ids,
            )
            offline.last_reply = reply
            self._speak_reply(reply, None, stop_event)
            return
        try:
            heard = offline.recognizer.listen(self._capture, stop_event)
        except Exception:
            logger.warning("local command recognizer failed", exc_info=True)
            return
        command = route_phrase(heard) if heard else None
        if command is None:
            if heard:
                offline.gate.offer(ReplayItem(item_id=uuid.uuid4().hex, text=heard))
            return
        reply = offline.router.handle(command)
        offline.last_reply = reply
        self._speak_reply(reply, command, stop_event)

    def _speak_reply(
        self, reply: Reply, command: LocalCommand | None, stop_event: threading.Event
    ) -> None:
        offline = self._offline
        assert offline is not None
        self._enter(FunnelState.SPEAKING)
        try:
            if command is LocalCommand.STOP:
                self._playback.stop()
                self._render(Cue(phase=Phase.CANCEL, cue_seq=self._next_cue_seq()))
            speaker = offline.speaker
            if speaker is not None and reply.clip_ids and speaker.can_say(reply.clip_ids):
                speaker.say(reply.clip_ids, stop_event=stop_event)
        except Exception:
            logger.warning("rung 1 reply failed", exc_info=True)
        finally:
            self._enter(FunnelState.IDLE)

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
            with self._capture_scope():
                stt_result = self._stt.run(self._capture)
        except Exception as exc:
            logger.warning("stt stream failed; back to idle", exc_info=True)
            # The listen cue already moved the head; a lost stream is a
            # lost turn, so it settles and is announced like any other.
            self._link_lost(f"speech stream lost: {exc}")
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
        react_move: str | None = None
        react_allowed = False
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
                if turn_event.react_move:
                    react_move = turn_event.react_move
                if turn_event.cue is not None:
                    if turn_event.cue.phase is Phase.SIGNAL:
                        react_allowed = turn_event.cue.react_allowed
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
        except (TurnLinkLost, requests.RequestException) as exc:
            logger.warning("turn stream link lost", exc_info=True)
            self._link_lost(f"turn stream lost: {exc}")
            self._enter(FunnelState.IDLE)
            return

        if cancelled or not reply_text:
            self._enter(FunnelState.IDLE)
            return

        announce = self._lost_turn_unannounced
        if announce and self._say_clip(RECONNECT_CLIP, "I'm back in touch with home."):
            # The clip is the line; it queues ahead of the reply's own audio.
            self._lost_turn_unannounced = False
            announce = False
        text = f"{LINK_RESTORED_LINE} {reply_text}" if announce else reply_text
        if not self._speak(text, turn_id, stop_event) and announce:
            self._lost_turn_unannounced = False
        self._enter(FunnelState.IDLE)
        if react_move and self._react_hook is not None and not stop_event.is_set():
            self._play_react(react_move, react_allowed)

    def _say_clip(self, clip_id: str, fallback_text: str | None = None) -> bool:
        """Speaks one offline clip when the bundle can; False when it cannot
        (no ladder, no speaker, unrendered clip, playback failure)."""
        speaker = self._offline.speaker if self._offline is not None else None
        if speaker is None:
            return False
        try:
            if hasattr(speaker, "say_phrase"):
                spoke = bool(speaker.say_phrase(clip_id, fallback_text=fallback_text))
                return spoke
            if not speaker.can_say([clip_id]):
                return False
            return bool(speaker.say([clip_id]))
        except Exception:
            logger.warning("offline clip %r failed", clip_id, exc_info=True)
            return False

    def _play_react(self, move: str, react_allowed: bool) -> None:
        """After the reply; move failure is logged and never loses the turn."""
        if self._motion.holding:
            logger.info("react move %r skipped: the body is held", move)
            return
        try:
            self._react_hook(
                move,
                ArbitrationState(),
                react_allowed=react_allowed,
                muted=self._is_muted(),
            )
        except Exception:
            logger.warning("react move %r failed", move, exc_info=True)

    def _speak(
        self, reply_text: str, turn_id: str | None, outer_stop_event: threading.Event
    ) -> bool:
        """Speak the reply; returns True when the link dropped under it."""
        self._enter(FunnelState.SPEAKING)
        barge_in = threading.Event()
        link_lost = threading.Event()

        def _on_first_chunk() -> None:
            self._render(Cue(phase=Phase.SPEAK, cue_seq=self._next_cue_seq()))

        speak_thread = threading.Thread(
            target=self._speak_worker,
            args=(reply_text, barge_in, _on_first_chunk, link_lost),
            daemon=True,
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
        if barge_in.is_set():
            return False
        if link_lost.is_set():
            # Mid-sentence loss: the reply was not finished, so this is a
            # cancel, never the settle a finished reply earns.
            self._link_lost("speech playback lost the hub")
            return True
        self._render(Cue(phase=Phase.DONE, cue_seq=self._next_cue_seq()))
        return False

    def _speak_worker(
        self,
        reply_text,
        stop_event: threading.Event,
        on_first_chunk,
        link_lost: threading.Event,
    ) -> None:
        try:
            self._tts.speak(reply_text, on_first_chunk=on_first_chunk, stop_event=stop_event)
        except (TtsLinkLost, requests.RequestException):
            logger.warning("tts playback failed", exc_info=True)
            link_lost.set()
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
            self._presence_tick(stop_event)

        if self._face_check_thread is not None:
            self._face_check_thread.join(timeout=_FACE_CHECK_JOIN_TIMEOUT_S)

    def _presence_tick(self, stop_event: threading.Event) -> None:
        try:
            observation = read_presence(self._client)
        except Exception:
            logger.warning("presence read failed", exc_info=True)
            return
        # Update the carry state first, so the tip/freefall override and the
        # latched held state describe the same IMU sample before any reaction.
        was_held = self._motion.holding
        self._motion_state = self._motion.update(observation.imu, self._motion_clock())
        held = self._motion.holding
        self._publish_motion_facts(
            held, self._motion_state in (MotionState.TIPPED, MotionState.FREEFALL)
        )
        self._on_freefall(observation.freefall_detected)
        arbitration = ArbitrationState(tracking_active=observation.face_detected)
        not_speaking = self._current_funnel() != FunnelState.SPEAKING
        should_track = (
            tracking_may_drive(arbitration)
            and not_speaking
            and self._tracking_allowed()
            and not held
        )
        with self._lock:
            already_tracking = self._state.tracking
        if should_track and not already_tracking:
            self._client.enable_tracking()
            with self._lock:
                self._state.tracking = True
            if self._on_change is not None:
                self._on_change()
        elif not should_track and already_tracking:
            self._client.disable_tracking()
            with self._lock:
                self._state.tracking = False
            if self._on_change is not None:
                self._on_change()

        try:
            if held and not was_held:
                self._on_lifted()
            elif was_held and not held:
                self._on_put_down()
        except Exception:
            logger.warning("carry hold handling failed", exc_info=True)

        if observation.face_detected:
            self._maybe_check_face(stop_event)

    def _publish_motion_facts(self, held: bool, alarm: bool) -> None:
        """Held and alarm are funnel facts for readers; told only when one flips."""
        with self._lock:
            if (self._state.held, self._state.alarm) == (held, alarm):
                return
            self._state.held, self._state.alarm = held, alarm
        self._emit_view()

    def _on_lifted(self) -> None:
        """Attempt each lift action independently; one failure must not skip the look."""

        def stop_head():
            return self._expression.render_primitive("stop", self._suppression_context())

        actions = [("head hold", stop_head)]
        if self._carry_gravity_compensation and not self._teach_active():
            actions.append(("gravity compensation", self._enable_carry_gravity_compensation))
        actions.append(("held look and line", self._carry_look_and_line))
        for name, action in actions:
            try:
                action()
            except Exception:
                logger.warning("carry %s failed", name, exc_info=True)

    def _enable_carry_gravity_compensation(self) -> None:
        self._client.enable_gravity_compensation()
        self._gravity_on_by_us = True

    def _carry_look_and_line(self) -> None:
        """The optional reaction to a lift, once. The holds above never depend on it."""
        reaction = self._carry_reaction()
        if reaction is CarryReaction.OFF or self._is_muted():
            return  # a muted body keeps its own antenna pose
        self._expression.render_held_look()
        if reaction is not CarryReaction.LOOK_AND_LINE:
            return
        if self._current_funnel() is not FunnelState.IDLE:
            return  # never over a turn
        entries = self._presence_entries() if self._presence_entries is not None else None
        if not line_allowed(entries):
            return  # a child, teen, unknown or nobody known: the silent look
        if self._say_clip(CARRY_LINES[self._carry_line_index % len(CARRY_LINES)]):
            self._carry_line_index += 1

    def _on_put_down(self) -> None:
        """After the stillness window (the machine's own): release what the lift
        took, settle once, and let tracking resume on the next tick."""
        if self._gravity_on_by_us:
            self._gravity_on_by_us = False
            self._client.disable_gravity_compensation()
        self._expression.render_primitive("settle", self._suppression_context())

    def _on_freefall(self, falling: bool) -> None:
        """One line per fall (design record section 7): said on the rising
        edge, never repeated while the body stays in the air, again after it
        has been steady. Motors-off and the state report are a separate item."""
        was_falling, self._freefall_active = self._freefall_active, falling
        if falling and not was_falling:
            self._say_clip(FREEFALL_CLIP, "Whoa, I tipped over.")

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
