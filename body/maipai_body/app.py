"""MaiPai Bot's Reachy Mini app: the daemon's one running app.

Registered under the ``reachy_mini_apps`` entry point (``pyproject.toml``)
as ``MaiPaiBody``. Builds the Reachy Mini client through the HAL seam
from the ``ReachyMini`` handle the daemon hands it, holds neutral, logs
one line per state change, and honors ``stop_event`` and SIGINT within
one second while unpaired; once G4's hub link reports paired, hands off
to G9's real ``ConversationLoop`` (audio, wake word, STT/turn/TTS
against the hub, expression, and FACE-01's face recognition) for the
rest of the process's life. ``run_paired_body`` is that whole path,
RM-03's own scaffold's real destination.

One caveat to the sub-second-stop contract, found by a code review
fixed by FACE-05: once paired, ``_build_conversation_loop`` runs on its
own daemon thread while this function polls ``stop_event``. A stop or
SIGINT mid-download is honored within one poll interval, abandoning the
in-progress build; that download continues or not on its own daemon
thread, which is moot since the process is exiting.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
import math
import os
import signal
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maipai_body.bodies.stackchan.companion import DIAGNOSTIC_KINDS
from maipai_body.bodies.stackchan.head_touch_filter import HEAD_KINDS, HeadTouchFilter
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.expression.suppression import SuppressionContext
from maipai_body.hal.errors import BodyLost
from maipai_body.hal.seam import AntennaPositions, HeadActuator, HeadPose, Indicator, NullIndicator
from maipai_body.indicator.director import EyesDirector
from maipai_body.indicator.live import LiveCaptureTap
from maipai_body.initiative.alarm import AlarmController, chime_samples
from maipai_body.link import HubLinkClient, PairingStore, discover_hub
from maipai_body.link.discovery import DiscoverHub
from maipai_body.link.lifecycle import LinkLifecycle
from maipai_body.link.offline import OfflineRungs
from maipai_body.link.prints import PrintSync
from maipai_body.link.roster import RosterPoller
from maipai_body.link.rung0 import Rung0Cues
from maipai_body.link.state import StateReporter
from maipai_body.link.state_machine import (
    DEFAULT_SLEEP_AFTER_MINUTES,
    LinkPhase,
    LinkStateMachine,
)
from maipai_body.link.supervisor import LinkSupervisor
from maipai_body.link.timesync import ClockSync, system_clock_setter
from maipai_body.moves.react import build_react_hook
from maipai_body.presence.entries import presence_entries_from
from maipai_body.presence.motor_health import MotorHealth
from maipai_body.presence.night import NightController
from maipai_body.presence.thermal import ThermalMonitor
from maipai_body.speech.capture import AudioCapture
from maipai_body.speech.follow_up import FollowUpPolicy, PeopleDirectory
from maipai_body.speech.models import EMBEDDING, MELSPECTROGRAM, WAKE_PHRASE, ensure_wakeword_models
from maipai_body.speech.offline_clips import (
    AssetUnavailable,
    ClipsUnavailable,
    CodeAnnouncer,
    ManifestError,
    OfflineSpeaker,
    alarm_child_clip_ids,
    alarm_clip_ids,
    ensure_clip_bundle,
)
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.stt_stream import SttStreamClient
from maipai_body.speech.tts_playback import TtsPlaybackClient
from maipai_body.speech.turn_client import TurnClient
from maipai_body.speech.wake import OpenWakeWordEngine, WakeScorer
from maipai_body.vision.embed import ensure_embedder
from maipai_body.vision.gallery import FaceGallery
from maipai_body.vision.models import SFACE

try:
    import reachy_mini
    from reachy_mini import ReachyMini, ReachyMiniApp

    from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
    from maipai_body.bodies.reachy_mini.eyes_client import EyesClient
    from maipai_body.bodies.reachy_mini.motors import DaemonMotorBus, MotorGate
    from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
    from maipai_body.run_loop import ConversationLoop
    from maipai_body.vision.watch import VisionWatch

    _reachy_imported = True
except ImportError:
    reachy_mini = None
    ReachyMini = Any
    _reachy_imported = False
    VisionWatch = Any

    class ReachyMiniApp:
        """Tiny runner shim used only by the standalone StackChan host."""

        settings_app = None

        def __init__(self, *args, **kwargs) -> None:
            pass

        def wrapped_run(self) -> None:
            self.run(None, threading.Event())

        def stop(self) -> None:
            pass

    class _MissingReachyClient:
        pass

    ReachyMiniClient = _MissingReachyClient
    EyesClient = Any
    DaemonMotorBus = Any
    MotorGate = Any
    REACHY_MINI_PROFILE = None

if _reachy_imported:
    from maipai_body.run_loop import ConversationLoop
    from maipai_body.vision.detect import FiveLandmarkDetector
else:
    ConversationLoop = None
    FiveLandmarkDetector = None


logger = logging.getLogger("maipai_body.app")

# Unit events that are logged one line each: the head touch kinds and the shake.
_LOGGED_UNIT_EVENTS = HEAD_KINDS | {"shake"}


def _stackchan_selected(environ: Mapping[str, str] | None = None) -> bool:
    """Whether this Bot process is configured to serve a StackChan body."""
    environ = os.environ if environ is None else environ
    return environ.get("MAIPAI_BODY", "reachy_mini").strip().lower() in {"stackchan", "fake"}


def _no_hub_discovery(timeout_s: float = 5.0):
    """An explicit Home URL is the configured trust anchor for sidecars."""
    return None


# The face watchdog (see StackChanBehavior.face_watchdog): quiet seconds before a stuck face is
# repaired, and how often the idle face is resent while all is well.
FACE_QUIET_S = 5.0
# While drowsy or asleep the unit is asked for touch events this often; wakes repeat no sooner.
LOOK_INTERVAL_S = 0.5  # two looks a second at most
TURN_FACE_FRESH_S = 5.0  # turn toward a face seen this recently when a turn starts
LOST_AFTER_LOOKS = 4  # two seconds without the face it was following: it was lost
TOUCH_POLL_S = 5.0
EVENT_POLL_S = 0.5  # touch, swipe and shake events are read this often while the robot is awake
TOUCH_WAKE_COOLDOWN_S = 30.0
FACE_REFRESH_S = 30.0


class StackChanBehavior:
    """Shared expression and bounded anonymous tracking for an attached StackChan."""

    def __init__(self, robot, *, vision_bridge=None, idle_interval_s: float = 8.0) -> None:
        from maipai_body.bodies.stackchan.gaze import GazeState
        from maipai_body.bodies.stackchan.presence_watch import CameraStats, GreetingPolicy
        from maipai_body.bodies.stackchan.profile import STACKCHAN_PROFILE
        from maipai_body.expression.engine import ExpressionEngine

        self.robot = robot
        self._holder = "stackchan-runtime"
        self._lock = threading.RLock()
        self._active = threading.Event()
        self._phase = "idle"
        self._closed = threading.Event()
        self._presence_stop: threading.Event | None = None
        self._presence_thread: threading.Thread | None = None
        self._vision = vision_bridge
        self._idle_interval_s = idle_interval_s
        self._last_idle = 0.0
        self._expression = ExpressionEngine(robot._driver("head"), STACKCHAN_PROFILE)
        # BOT-FACE-NIGHT-01: at night no idle or tracking gestures; set by the night rule.
        self.night_active: Callable[[], bool] = lambda: False
        # Charging or on USB power: no wandering. Set by the power rule (power_idle.py).
        self.idle_still: Callable[[], bool] = lambda: False
        # robot.idle.level from the settings frame (still, calm, lively). Still until the hub says
        # otherwise: a fresh or lost-settings unit never wanders (owner request 2026-10-20).
        self.idle_level = "still"
        # True once any move left the head off centre; the post-turn settle only runs then.
        self._head_off_centre = False
        self._hold_until = float("-inf")
        # Touch, swipe and shake events from the unit (patch 021) wake a drowsy or sleeping robot.
        # Set by the service wiring; None means no unit events are available.
        self.event_poll: Callable[[], list] | None = None
        self.unit_facts: Any = (
            None  # link.checkin.UnitFacts: the latest boot, memory and firmware facts
        )
        # The unit's own volume and brightness sliders: (volume, brightness), either may be None.
        self.on_levels_changed: Callable[[int | None, int | None], None] | None = None
        # Gets the kinds of the events read ("head_touch", "shake", ...); set by the service wiring.
        self.reaction: Callable[[list[str]], object] | None = None
        self.reaction_tick: Callable[[], object] | None = None
        # Orientation: the pose logic, its timer, and whether a pose face is being held.
        self.orientation: Any = None
        self.vision_poster: Any = None  # vision_post.VisionPoster: scene descriptions from Home
        self._vision_posting = False
        self._vision_last: tuple[str | None, Any] | None = None  # bucket and thumbnail last posted
        self.orientation_tick: Callable[[], object] | None = None
        self.pose_held: Callable[[], bool] = lambda: False
        self._last_event_poll = float("-inf")
        self._last_touch_wake = float("-inf")
        self._event_queue_drained = False
        self._head_filter = HeadTouchFilter()
        # Idle face watching: the camera level from the settings frame, the greeting style, and
        # the counters of the unit's camera stream (all set by the service wiring).
        self.watch_level: Callable[[], str] = lambda: "identify"
        self.greeting_mode = "gesture"
        self.camera_counters: Callable[[], tuple[int, int]] = lambda: (0, 0)
        self._camera_stats = CameraStats(lambda: self.camera_counters())
        self._greeting = GreetingPolicy()
        self._last_look = float("-inf")
        self._followed = False
        self._missed_looks = 0
        # The most recent face (frame x, y and when), for turning toward the speaker.
        self._last_face: tuple[float, float, float] | None = None
        self._turn_face_held = False
        self._warned: dict[str, float] = {}
        self.on_idle_level: Callable[[], None] = lambda: None
        # BOT-SC-ANIM-01: drowsy and asleep stages so an idle robot does not sit smiling for hours.
        from maipai_body.bodies.stackchan.profile import STACKCHAN_PROFILE as _profile
        from maipai_body.bodies.stackchan.routines import RestRenderer
        from maipai_body.expression.rest import RestPolicy

        self._rest = RestPolicy(
            time.monotonic(),
            drowsy_after_s=120.0,
            asleep_after_s=300.0,
            quiet_hours_active=lambda: self.night_active(),
        )
        # Why the head is where it is, for "what are you looking at?" (gaze.py).
        self.gaze = GazeState(
            asleep=lambda: self._rest.stage != "awake" or self.night_active(),
            wandering=lambda: not self.idle_still(),
        )
        from maipai_body.bodies.stackchan.head_gate import HeadMotionGate

        self.head_gate = HeadMotionGate(
            must_be_still=lambda: self.idle_still(), resting=lambda: self._rest.stage != "awake"
        )
        self._rest_renderer = RestRenderer()
        self._rest_profile = _profile
        self._last_person_seen = float("-inf")
        self._face_quiet_since: float | None = None
        self._face_refreshed_at = float("-inf")
        self._night_turned = False

    @property
    def presence_thread_alive(self) -> bool:
        return self._presence_thread is not None and self._presence_thread.is_alive()

    def _with_lease(self, callback):
        with self._lock:
            holder = self.robot.lease_holder
            if holder is None:
                self.robot.lease.acquire(priority="expression", holder=self._holder)
            elif holder != self._holder:
                return False
            try:
                callback()
            finally:
                if self.robot.lease_holder == self._holder:
                    self.robot.lease.release(holder=self._holder)
            return True

    def hold_pose(self, seconds: float) -> None:
        """Keep the post-turn settle from undoing a head pose the person just asked for."""
        self._hold_until = time.monotonic() + seconds

    def render_primitive(self, primitive: str) -> bool:
        if self.night_active() or self.pose_held():
            return False
        # Ambient moves (the idle settle, face following) go through the one head-motion gate.
        if not self.head_gate.allow(f"ambient:{primitive}", response=self._active.is_set()):
            return False
        self._head_off_centre = True
        return self._with_lease(
            lambda: self._expression.render_ambient(primitive, SuppressionContext())
        )

    def render_turn_state(self, state: str, *, mood: str | None = None) -> None:
        self._active.set()
        # "listening" leaves room for a pet's face; thinking and speaking own the face and voice.
        self._phase = {"listening": "listening", "settle": "idle"}.get(state, "busy")
        # Only states that really move the head ask the gate (and count toward its cap); the
        # settle back to centre is essential and always passes.
        moves = state in {"listening", "thinking", "speaking"}
        may_move = (
            self.head_gate.allow(f"turn:{state}", response=True)
            if moves
            else self.head_gate.allow(f"turn:{state}", essential=True)
            if state == "settle"
            else True
        )
        if state == "thinking":
            from maipai_body.bodies.stackchan.gaze import GazeReason

            self.gaze.note(GazeReason.THINKING)
        if self.night_active():
            # One head turn to face whoever speaks, then rest; no other gestures.
            if state == "listening" and not self._night_turned:
                self._night_turned = True
                if may_move:
                    self._head_off_centre = True
                    self._with_lease(
                        lambda: self._expression.render_ambient("attend", SuppressionContext())
                    )
            if state == "settle":
                self._night_turned = False
                self._active.clear()
            return
        self._night_turned = False
        primitive = {
            "listening": "perk",  # head lifts and the face brightens: it heard you
            "thinking": "attend",
            "speaking": "speak",
        }.get(state)

        def render() -> None:
            if state == "settle":
                self._turn_face_held = False
                # Only a head that actually left centre is brought back: a quiet turn that moved
                # nothing must not move the head again (the unit was settling after every turn).
                if self._head_off_centre and may_move and time.monotonic() >= self._hold_until:
                    self._head_off_centre = False
                    self._expression.render_ambient("settle", SuppressionContext())
                return
            self._expression.render_turn_state(state, mood=mood)
            if state == "listening":
                self._turn_face_held = may_move and self._turn_toward_face()
            if primitive is not None and may_move and not self._turn_face_held:
                self._head_off_centre = True
                self._expression.render_ambient(primitive, SuppressionContext())
            elif state == "reply_mood":
                self._expression.render_turn_state("reply_mood", mood=mood)

        try:
            self._with_lease(render)
        finally:
            if state == "settle":
                self._active.clear()

    def start_presence(self, stop_event: threading.Event) -> None:
        if self._presence_thread is not None:
            return
        self._presence_stop = threading.Event()
        try:
            # Local watching: silent, and only while robot.camera.watch_level is not "off".
            self.robot.camera.stream(enabled=True, silent=True)
        except Exception:
            logger.warning("StackChan camera stream could not start", exc_info=True)
        self._presence_thread = threading.Thread(
            target=self._presence_loop,
            args=(stop_event, self._presence_stop),
            name="stackchan-presence",
            daemon=True,
        )
        self._presence_thread.start()

    def _presence_loop(self, stop_event: threading.Event, local_stop: threading.Event) -> None:
        while not stop_event.is_set() and not local_stop.wait(0.2):
            if self._closed.is_set():
                return
            now = time.monotonic()
            if (
                not self._active.is_set()
                and not self.idle_still()
                and now - self._last_idle >= self._idle_interval_s
            ):
                self._last_idle = now
                try:
                    self.render_primitive("settle")
                except Exception:
                    self._warn_limited("idle", "StackChan idle expression failed")
            try:
                self.watch_for_faces(now)
                self.post_scene(now)
            except Exception:
                self._warn_limited("tracking", "StackChan face watching failed")
            line = self._camera_stats.report(now)
            if line:
                logger.info(line)
            if self._vision is not None:
                check = self._vision.frame_check.report(now)
                if check:
                    logger.info(check)
            try:
                self.wake_on_touch(now)
            except Exception:
                self._warn_limited("touch", "StackChan touch wake check failed")
            if self.reaction_tick is not None:
                try:
                    self.reaction_tick()
                except Exception:
                    self._warn_limited("reaction", "StackChan reaction timer failed")
            if self.orientation_tick is not None:
                try:
                    self.orientation_tick()
                except Exception:
                    self._warn_limited("orientation", "StackChan orientation timer failed")
            try:
                self.rest_step(now)
            except Exception:
                self._warn_limited("rest", "StackChan rest routine failed")
            try:
                self.face_watchdog(now)
            except Exception:
                self._warn_limited("watchdog", "StackChan face watchdog failed")

    def post_scene(self, now: float) -> None:
        """Send Home one camera picture now and then so it can describe the room (never in a turn).

        Idle only, not at night, not when watching is off, not while a post is on its way. A picture
        goes at once when the brightness bucket changed (at most every 10 s), otherwise once a
        minute if the scene differs from the last one posted and every five minutes even if not
        (each picture costs Home a model call); the frame is dropped as soon as it is posted."""
        poster = self.vision_poster
        if (
            poster is None
            or self._vision is None
            or self._vision_posting
            or self._active.is_set()
            or self.night_active()
            or self.watch_level() == "off"
        ):
            return
        from maipai_body.bodies.stackchan.vision_post import differs, light_bucket

        look = self._vision.latest_look(max_age_s=3.0)
        if look is None:
            return
        _jpeg, people, luma, thumb = look
        bucket = light_bucket(luma)
        last_bucket, last_thumb = self._vision_last or (None, None)
        due = poster.scene_due(
            now,
            bucket_changed=self._vision_last is not None and bucket != last_bucket,
            differs=differs(thumb, last_thumb),
        )
        if not due:
            return
        taken = self._vision.latest_look(max_age_s=3.0, take=True)
        if taken is None:
            return
        state = (bucket, thumb)
        self._vision_posting = True
        threading.Thread(
            target=self._post_scene_now,
            args=(taken[0], people, bucket, state),
            name="stackchan-vision-post",
            daemon=True,
        ).start()

    def _post_scene_now(
        self, jpeg: bytes, people: int, bucket: str | None, state: tuple[str | None, Any]
    ) -> None:
        try:
            result = self.vision_poster.post(jpeg, purpose="scene", people=people, light=bucket)
            if result.ok:
                self._vision_last = state
        except Exception:
            self._warn_limited("vision", "StackChan scene post failed")
        finally:
            self._vision_posting = False

    def vision_ask(self, kind: str) -> bool:
        """Post a picture for a question about what it sees; True when Home described it.

        Camera frames pause while a turn is on, so this uses the newest picture from just before
        the person spoke to the robot. Nothing is kept: the picture is posted and dropped."""
        poster = self.vision_poster
        if (
            poster is None
            or self._vision is None
            or self.watch_level() == "off"
            or not poster.ask_possible()
        ):
            return False
        from maipai_body.bodies.stackchan.vision_post import light_bucket

        look = self._vision.latest_look(max_age_s=20.0, take=True)
        if look is None:
            return False
        jpeg, people, luma, _thumb = look
        result = poster.post(
            jpeg, purpose="ask", people=people, light=light_bucket(luma), timeout=5.0
        )
        return result.ok

    def watch_for_faces(self, now: float) -> bool:
        """Look for a face in the unit's latest camera frame about twice a second.

        Local only: the frame is decoded and searched in memory and only "a face was there" is
        kept. Off while a turn is on, at night, and when the camera level is off. The head follows
        a face only when the head gate allows it; the room counts as occupied either way, which
        keeps the rest policy awake and, after a long empty spell, gives one greeting."""
        if (
            self._vision is None
            or self._active.is_set()
            or self.night_active()
            or self.watch_level() == "off"
            or now - self._last_look < LOOK_INTERVAL_S
        ):
            return False
        self._last_look = now
        started = time.monotonic()
        self._followed = False
        target = self._vision.track_stream_frame(deadline_s=0.4, may_move=self._may_follow)
        self._camera_stats.looked(time.monotonic() - started, target.detected)
        from maipai_body.bodies.stackchan.gaze import GazeReason

        if not target.detected:
            self._missed_looks += 1
            if (
                self._missed_looks == LOST_AFTER_LOOKS
                and self.gaze.reason is GazeReason.TRACK
                and self.gaze.current() is GazeReason.TRACK
            ):
                self.gaze.note(GazeReason.SEARCH)  # a face it was following is gone
            return False
        self._missed_looks = 0
        self._last_person_seen = now
        if target.x is not None and target.y is not None:
            self._last_face = (target.x, target.y, now)
        if self._followed:
            self.gaze.note(GazeReason.TRACK)
        if self._greeting.seen(now):
            self.greet()
        return True

    def face_age(self) -> float | None:
        """Seconds since a face was last seen, or None if none has been."""
        return None if self._last_face is None else time.monotonic() - self._last_face[2]

    def _turn_toward_face(self) -> bool:
        """On listen start, turn toward the face seen a moment ago and hold the turn through the
        reply. Nothing happens when no face was seen in the last few seconds (no hunting)."""
        face = self._last_face
        if face is None or time.monotonic() - face[2] > TURN_FACE_FRESH_S:
            return False
        from maipai_body.bodies.stackchan.gaze import GazeReason
        from maipai_body.bodies.stackchan.vision_bridge import follow_pose
        from maipai_body.hal.seam import FaceTrackTarget

        pose = follow_pose(FaceTrackTarget(detected=True, x=face[0], y=face[1]))
        self.robot.head.set(pose=pose)  # the lease is held by the turn state that called this
        self._head_off_centre = True
        self.gaze.note(GazeReason.TRACK)
        logger.info("StackChan turned toward the speaker")
        return True

    def _may_follow(self) -> bool:
        self._followed = (not self.idle_still()) and self.head_gate.allow("ambient:track")
        return self._followed

    def greet(self) -> None:
        """A gesture greeting: a happy face for a moment, and a nod when the head may move.

        Spoken greetings belong to Home's person and age rules; the robot only gestures."""
        if self.greeting_mode == "off":
            return
        logger.info("StackChan greeting: someone came into view after a long while")
        device = self.robot._driver("head").expression_device
        if device is not None:
            from maipai_body.bodies.stackchan.avatar.server import control_avatar

            device.send_avatar_frame(control_avatar("happy"))  # the face watchdog restores it
        if not self.idle_still():
            self.render_primitive("nod")

    def reaction_blocked(self) -> bool:
        """True while the robot is thinking or speaking: a touch reaction is not shown then."""
        return self._active.is_set() and self._phase != "listening"

    def show_face(self, expression: str, *, while_listening: bool = False) -> None:
        """Show a face for a moment; the face watchdog puts the idle face back.

        Not during a turn, except a reaction face while the robot is only listening."""
        if self._active.is_set() and not (while_listening and self._phase == "listening"):
            return
        device = self.robot._driver("head").expression_device
        if device is None:
            return
        from maipai_body.bodies.stackchan.avatar.server import control_avatar

        device.send_avatar_frame(control_avatar(expression))
        self._face_quiet_since = None  # the watchdog counts its quiet time from now

    def wake_on_touch(self, now: float) -> bool:
        """Read the unit's touch, swipe and shake events; wake a sleeper, tell the reactions.

        The unit is asked every ``EVENT_POLL_S`` while awake and every ``TOUCH_POLL_S`` while
        drowsy or asleep, during a turn too (a pat while it only listens must react; the reactions
        decide what to show). The first look after a pause only empties the unit's queue (old events
        are not a reason to react). True when it woke the robot."""
        if self.event_poll is None:
            self._event_queue_drained = False
            return False
        asleep = self._rest.stage != "awake"
        if now - self._last_event_poll < (TOUCH_POLL_S if asleep else EVENT_POLL_S):
            return False
        paused = now - self._last_event_poll > 30.0
        self._last_event_poll = now
        events = self.event_poll()
        # A slider the person moved on the unit is a level to keep, never old news to drain.
        for event in events:
            if getattr(event, "kind", None) == "level_changed" and self.on_levels_changed:
                try:
                    self.on_levels_changed(
                        getattr(event, "volume", None), getattr(event, "brightness", None)
                    )
                except Exception:
                    self._warn_limited("levels", "StackChan level sync failed")
        events = [e for e in events if getattr(e, "kind", None) != "level_changed"]
        for event in events:
            if getattr(event, "kind", None) in DIAGNOSTIC_KINDS:
                extra = getattr(event, "extra", None) or {}
                if self.unit_facts is not None:
                    self.unit_facts.observe(event.kind, extra)
                if event.kind == "stop_word" and "cmd" in extra:
                    verdict = "accepted" if extra.get("accepted") else "rejected"
                    logger.info(
                        "unit stop word: heard %r, score %s, second %s (%s)",
                        extra.get("cmd"),
                        extra.get("score"),
                        extra.get("second"),
                        verdict,
                    )
                    continue
                if event.kind == "orientation" and self.orientation is not None:
                    try:
                        self.orientation.on_event(extra)
                    except Exception:
                        self._warn_limited("orientation", "StackChan orientation reaction failed")
                detail = " ".join(f"{k}={v}" for k, v in extra.items())
                label = {
                    "stop_word": "unit stop word",
                    "fw": "unit firmware",
                    "camera": "unit camera",
                    "barge_stats": "unit barge",
                    "orientation": "unit orientation",
                    "playback": "unit playback",
                    "heap_stats": "unit memory",
                    "stack_stats": "unit memory",
                    "boot": "unit boot",
                    "tap": "unit tap",
                    "wake": "unit wake",
                    "wake_stats": "unit wake",
                    "state_guard": "unit wake",
                }.get(event.kind, "unit touch")
                logger.info("%s: %s %s", label, event.kind, detail)
        events = [e for e in events if getattr(e, "kind", None) not in DIAGNOSTIC_KINDS]
        events = self._head_filter.accept(now, events)
        for event in events:
            if getattr(event, "kind", None) in _LOGGED_UNIT_EVENTS:
                extra = getattr(event, "extra", None) or {}
                detail = " ".join(f"{k}={v}" for k, v in extra.items())
                logger.info(
                    "unit touch: %s %s%s",
                    event.kind,
                    detail,
                    " (first look after a pause: not acted on)"
                    if paused or not self._event_queue_drained
                    else "",
                )
        if paused or not self._event_queue_drained:
            self._event_queue_drained = True
            return False
        if not events:
            return False
        kinds = [str(getattr(event, "kind", event)) for event in events]
        if self.reaction is not None:
            try:
                self.reaction(kinds)
            except Exception:
                self._warn_limited("reaction", "StackChan touch reaction failed")
        if not asleep or now - self._last_touch_wake < TOUCH_WAKE_COOLDOWN_S:
            return False
        self._last_touch_wake = now
        self._last_person_seen = now  # the rest policy treats a person as activity and wakes
        logger.info("StackChan woke up on touch (%s)", ", ".join(sorted(set(kinds))))
        return True

    def _warn_limited(self, key: str, message: str) -> None:
        """One warning with its traceback per minute per cause: a loop that fails five times a
        second while the unit is away logged 378 tracebacks in nine minutes."""
        now = time.monotonic()
        if now - self._warned.get(key, float("-inf")) >= 60.0:
            self._warned[key] = now
            logger.warning(message, exc_info=True)

    def face_watchdog(self, now: float) -> bool:
        """Never leave the face stuck (eyes shut, mouth open) after a lost frame or an odd exit.

        With no turn active for ``FACE_QUIET_S`` and the rest policy awake, resend the idle face
        once if the last frame was not idle (or never arrived), then every ``FACE_REFRESH_S``.
        """
        if self._active.is_set() or self.pose_held():
            self._face_quiet_since = None
            return False
        if self._face_quiet_since is None:
            self._face_quiet_since = now
            return False
        if self._rest.stage != "awake" or self.night_active():
            return False
        device = self.robot._driver("head").expression_device
        if device is None:
            return False
        stale = (
            device.last_expression != "neutral"
            or not device.last_expression_ok
            or now - self._face_refreshed_at >= FACE_REFRESH_S
        )
        if not stale or now - self._face_quiet_since < FACE_QUIET_S:
            return False
        from maipai_body.bodies.stackchan.avatar.server import control_avatar

        device.send_avatar_frame(control_avatar("neutral"))
        self._face_refreshed_at = now
        return True

    def rest_step(self, now: float) -> str:
        """One pass of the rest policy: drop the head and sleepy face after a long quiet spell."""
        person = now - self._last_person_seen < 30.0
        output = self._rest.update(now, person_present=person, turn_active=self._active.is_set())
        self._with_lease(
            lambda: self._rest_renderer.render(
                output,
                self.robot._driver("head"),
                self._rest_profile,
                pose_held=self.pose_held,
            )
        )
        return output.stage

    def stop_presence(self) -> None:
        if self._presence_stop is not None:
            self._presence_stop.set()
        if self._presence_thread is not None:
            self._presence_thread.join(timeout=2.0)
            self._presence_thread = None
        try:
            self.robot.camera.stream(enabled=False)
        except Exception:
            logger.debug("StackChan camera stream already stopped", exc_info=True)

    def close(self) -> None:
        self._closed.set()
        self.stop_presence()
        close = getattr(self._vision, "close", None)
        if callable(close):
            close()
        self._expression.close()
        holder = self.robot.lease_holder
        if holder is not None:
            self.robot.lease.release(holder=holder)


def _start_stackchan_night(
    voice, behavior: StackChanBehavior, link: LinkLifecycle | None, stop_event: threading.Event
) -> NightController:
    """BOT-FACE-NIGHT-01: the face color and night rule on a StackChan.

    The hub's `settings_changed` reaches it through the same `CommandChannel` the
    Reachy body uses, started here because this body has no conversation loop."""
    from maipai_body.bodies.stackchan.owner_levels import OwnerLevels
    from maipai_body.link.channel import CommandChannel
    from maipai_body.presence.sleep_auto import QuietHours, luma_reader

    quiet = QuietHours()
    watch = ["identify"]  # the default until the hub says otherwise

    class _StreamCamera:
        def get_frame(self):
            data = voice.robot.robot._driver("camera").stream_frame(0.4)
            if not data:
                return None
            from maipai_body.bodies.stackchan.vision_bridge import _decode_jpeg

            return _decode_jpeg(data)

    def leds(on: bool) -> None:
        if not on:  # back on: the expression engine repaints the ring itself
            voice.robot.robot.leds.many([{"index": i, "rgb": [0, 0, 0]} for i in range(12)])

    levels = OwnerLevels(_data_dir() / "owner_levels.json")
    levels.load()

    night = NightController(
        voice.robot.client,
        clock=time.monotonic,
        quiet_hours=quiet.active,
        watch_level=lambda: watch[0],
        camera_luma=luma_reader(_StreamCamera(), level=lambda: watch[0]),
        leds=leds,
        levels=levels,
        connected=lambda: bool(voice._sessions),
    )
    voice.session_listeners.append(lambda _device_id: night.on_connect())
    behavior.night_active = lambda: night.night
    behavior.watch_level = lambda: watch[0]
    voice.robot.robot._driver("camera").watch_allowed = lambda: watch[0] != "off"

    def apply_settings(payload: dict) -> None:
        values = payload.get("values")
        if not isinstance(values, dict):
            return
        quiet.apply(values)
        level = values.get("robot.camera.watch_level")
        if level in ("off", "presence", "identify"):
            was_off = watch[0] == "off"
            watch[0] = level
            try:
                if level == "off":
                    behavior.robot.camera.stream(enabled=False)
                elif was_off:
                    behavior.robot.camera.stream(enabled=True, silent=True)
            except Exception:
                logger.warning("StackChan camera watch level change failed", exc_info=True)
        greeting = values.get("robot.greetings.mode")
        if greeting in ("off", "gesture", "spoken"):
            behavior.greeting_mode = greeting
        idle = values.get("robot.idle.level")
        if idle in ("still", "calm", "lively"):
            # "calm" is Home's registry default, so it cannot be told from a deliberate choice;
            # a robot that wanders on its own by default wore servos (2026-10-21), so calm counts
            # as still until the default itself changes. "lively" is always a choice.
            behavior.idle_level = _effective_idle_level(idle)
            behavior.on_idle_level()
        if "robot.vision" in values and behavior.vision_poster is not None:
            behavior.vision_poster.set_mode(values.get("robot.vision"))
        night.apply_settings(values)

    if link is not None:
        channel = CommandChannel(
            "",
            "",
            credentials=_command_credentials(link),
            settings_handler=apply_settings,
            on_drop=link.channel_lost,
        )
        threading.Thread(
            target=channel.run, args=(stop_event,), name="stackchan-command-channel", daemon=True
        ).start()
    threading.Thread(
        target=night.run, args=(stop_event,), name="stackchan-night", daemon=True
    ).start()
    return night


def _turn_sink(behavior, light):
    """One turn event: move the face and set the ring's funnel state (the light standard).

    Wake word or tap opens a turn as ``listening`` (blue steady, eyes widen); the live cue (green)
    takes over while audio streams to the hub; thinking breathes magenta; speaking is white.
    """
    from maipai_body.presence.funnel import FunnelState

    funnel = {
        "listening": FunnelState.LISTENING,
        "thinking": FunnelState.THINKING,
        "speaking": FunnelState.SPEAKING,
        "settle": FunnelState.IDLE,
    }

    def sink(state: str, *, mood: str | None = None) -> None:
        next_state = funnel.get(state)
        if next_state is not None:
            try:
                light.update(funnel=next_state)
            except Exception:  # a light never fails the turn
                logger.warning("StackChan funnel light failed", exc_info=True)
        behavior.render_turn_state(state, mood=mood)

    return sink


async def _serve_stackchan_channels(
    stop_event: threading.Event,
    host: str,
    xiaozhi_port: int,
    avatar_host: str,
    avatar_port: int,
    link: LinkLifecycle | None = None,
    offline: OfflineRungs | None = None,
) -> None:
    from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
    from maipai_body.bodies.stackchan.avatar.server import AvatarServer
    from maipai_body.bodies.stackchan.turn import StackChanTurnBridge
    from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore, default_pairing_path
    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient, XiaozhiServer
    from maipai_body.bodies.stackchan.xiaozhi.tls import server_ssl_context

    vision_host = os.environ.get("MAIPAI_VISION_HOST", host)
    try:
        vision_port = int(os.environ.get("MAIPAI_VISION_PORT", "8767"))
    except ValueError as exc:
        raise ValueError("MAIPAI_VISION_PORT must be a TCP port number.") from exc
    pairing = PairingStore(default_pairing_path())
    voice = XiaozhiServer(
        pairing,
        robot=None,
        vision_host=vision_host,
        vision_port=vision_port,
        advertised_vision_url=os.environ.get("MAIPAI_VISION_URL"),
    )
    avatar = AvatarServer(pairing)
    cert_path = os.environ.get("MAIPAI_XIAOZHI_TLS_CERT")
    key_path = os.environ.get("MAIPAI_XIAOZHI_TLS_KEY")
    tls_context = server_ssl_context(cert_path, key_path)
    voice.robot = StackChanRobotAdapter(XiaozhiDeviceClient(voice))
    voice._avatar_frame_sender = avatar.send_frame
    camera_driver = voice.robot.robot._driver("camera")
    avatar.start_camera_on_connect = lambda: (
        not voice.robot.robot.estop_engaged and camera_driver.watch_allowed()
    )
    vision = None
    try:
        from maipai_body.bodies.stackchan.vision_bridge import StackChanVisionBridge
        from maipai_body.vision.yunet import LazyFaceDetector

        # The pinned YuNet model comes from Home like every other model; until it has been synced
        # the detector finds nothing and says so once every ten minutes.
        vision = StackChanVisionBridge(
            voice.robot.robot,
            detector=LazyFaceDetector(lambda: _load_yunet_model(link)),
            embedder=None,
            gallery=None,
        )
    except Exception as exc:
        # One line, not a traceback: the cause is almost always a package the bundle lacks.
        logger.warning("StackChan face watching is unavailable (%s: %s)", type(exc).__name__, exc)
    behavior = StackChanBehavior(voice.robot.robot, vision_bridge=vision)
    behavior.camera_counters = lambda: (
        avatar.camera_frames_received,
        avatar.camera_bytes_received,
    )
    behavior.event_poll = voice.robot.client.companion().poll_events
    if link is not None:
        from maipai_body.bodies.stackchan.vision_post import PICTURE_POSTS_ENABLED, VisionPoster

        if PICTURE_POSTS_ENABLED:
            behavior.vision_poster = VisionPoster(_hub_credentials_reader(link, ""))
    if link is not None:
        _start_robot_checkin(voice, behavior, link, stop_event)
    night = _start_stackchan_night(voice, behavior, link, stop_event)
    behavior._rest_renderer._set_brightness = night._device.set_brightness
    behavior._rest_renderer._restore_brightness = night.effective_brightness
    behavior.on_levels_changed = night.set_levels_from_unit
    from maipai_body.bodies.stackchan.power_idle import PowerIdle

    power = PowerIdle(
        voice.robot.client.set_idle_motion,
        night_active=lambda: night.night,
        configured_level=lambda: behavior.idle_level,
    )
    behavior.on_idle_level = power.refresh
    night.after_edge = power.refresh
    voice.session_listeners.append(lambda _device_id: power.on_reconnect())

    def _power_ticks() -> None:
        while not stop_event.wait(1.0):
            try:
                power.tick()
            except Exception:
                logger.warning("StackChan power rule failed", exc_info=True)

    threading.Thread(target=_power_ticks, name="stackchan-power-idle", daemon=True).start()
    behavior.idle_still = lambda: power.still
    from maipai_body.bodies.stackchan.light_wiring import start_stackchan_light

    def device_connected() -> bool:
        return bool(voice._sessions)

    light = start_stackchan_light(
        voice.robot,
        offline,
        stop_event,
        device_connected=device_connected,
        on_battery=power.on_battery_status,
    )
    behavior._rest_renderer._set_ring_sleeping = light.set_sleeping
    from maipai_body.bodies.stackchan.estop_recovery import EstopRecovery

    def device_answers() -> bool:
        """A real answer from the unit (a connected socket is not enough during a freeze)."""
        try:
            voice.robot.client.get_head_angles()
        except Exception:
            return False
        return True

    threading.Thread(
        target=EstopRecovery(voice.robot.robot, device_answers).run,
        args=(stop_event,),
        name="stackchan-estop-recovery",
        daemon=True,
    ).start()
    voice.robot.robot._driver("camera").cue_sink = light.cue_camera
    from maipai_body.bodies.stackchan.uplink_stats import UplinkStats

    uplink = UplinkStats()
    if link is not None and offline is not None:
        import math

        from maipai_body.bodies.stackchan.brightness import BrightnessControl
        from maipai_body.bodies.stackchan.head_commands import HeadCommander
        from maipai_body.bodies.stackchan.volume import VolumeControl
        from maipai_body.hal.seam import HeadPose

        def _move_head(yaw_deg: int, pitch_deg: int, speed: int) -> None:
            pose = HeadPose(yaw=math.radians(yaw_deg), pitch=math.radians(pitch_deg))
            if not behavior._with_lease(lambda: voice.robot.robot.head.set(pose=pose, speed=speed)):
                raise RuntimeError("another part of the robot is using the head")

        def _head_blocked() -> str | None:
            if voice.robot.robot.estop_engaged:
                return "the emergency stop is latched"
            if power.charging:
                return "the unit is charging"
            return None

        from maipai_body.bodies.stackchan.gaze import GazeReason
        from maipai_body.bodies.stackchan.sight import SightAnswers

        head_commander = HeadCommander(
            _move_head,
            blocked=_head_blocked,
            hold_pose=behavior.hold_pose,
            on_done=lambda command: behavior.gaze.note(
                GazeReason.COMMAND, command.direction or command.kind
            ),
        )

        bridge = StackChanTurnBridge(
            voice,
            link,
            offline,
            cache_dir=_default_models_cache_dir(),
            # The current /api/stt/stream contract has no speaker field.
            # This adapter consumes that field when the hub adds it; absent
            # results remain anonymous on this turn.
            person_attribution=lambda result: getattr(result, "speaker_evidence", None),
            expression_sink=_turn_sink(behavior, light),
            live_sink=light.cue_live,
            uplink_stats=uplink,
            volume_control=VolumeControl(
                voice.robot.client._call,
                voice.robot.client.set_volume,
                on_set=lambda level, _command: night.set_owner_volume_from_voice(level),
            ),
            brightness_control=BrightnessControl(
                night.effective_brightness, night.set_brightness_from_voice
            ),
            head_control=head_commander,
            gaze_control=behavior.gaze,
            sight_control=SightAnswers(
                face_age=behavior.face_age,
                camera_on=lambda: behavior.watch_level() != "off",
                light=lambda: _light_from_last_look(
                    vision, getattr(voice.robot.client, "last_lux", None)
                ),
                camera_running_s=avatar.camera_running_s,
            ),
        )
        bridge.vision_ask = behavior.vision_ask
        voice.audio_handler = bridge.on_audio
        voice.turn_handler = bridge.listen
        from maipai_body.bodies.stackchan.reactions import Reactions

        reactions = Reactions(
            face=lambda expression: behavior.show_face(expression, while_listening=True),
            say=bridge.speak_reaction,
            quiet=lambda: night.night,
            busy=behavior.reaction_blocked,
            symbol=lambda name: voice.robot.client._call(
                "self.screen.show_symbol", {"name": name, "ms": 2500}
            ),
        )
        behavior.reaction = reactions.on_events
        behavior.reaction_tick = reactions.tick
        _wire_orientation(voice, behavior, bridge, night, power)
        bridge.on_user_words = reactions.on_user_words
        bridge.on_reply_mood = reactions.on_reply_mood
        from maipai_body.selftest.stackchan_wiring import build_context, build_service_hooks
        from maipai_body.speech.turn_client import TurnClient

        voice.selftest_checks, voice.selftest_runner = build_service_hooks(
            build_context(
                robot=voice.robot.robot,
                client=voice.robot.client,
                light=light,
                uplink=uplink,
                link=link,
                turn_factory=TurnClient,
            ),
            light,
        )
    await voice.start(host, xiaozhi_port, ssl=tls_context)
    try:
        await avatar.start(avatar_host, avatar_port, ssl=tls_context)
        scheme = "wss" if cert_path else "ws"
        logger.info(
            "StackChan xiaozhi and avatar services listening on %s://%s:%s and %s://%s:%s",
            scheme,
            host,
            xiaozhi_port,
            scheme,
            avatar_host,
            avatar_port,
        )
        while not stop_event.is_set() and not voice._session_ready.is_set():
            await asyncio.sleep(0.1)
        if voice._session_ready.is_set() and not stop_event.is_set():
            # start_presence makes device calls that wait on this loop: run it off the loop.
            await asyncio.to_thread(behavior.start_presence, stop_event)
        await asyncio.to_thread(stop_event.wait)
    finally:
        behavior.close()
        await avatar.close()
        await voice.close()


def _run_stackchan_service(
    stop_event: threading.Event,
    link: LinkLifecycle | None = None,
    offline: OfflineRungs | None = None,
) -> None:
    host = os.environ.get("MAIPAI_XIAOZHI_HOST", "127.0.0.1")
    try:
        xiaozhi_port = int(os.environ.get("MAIPAI_XIAOZHI_PORT", "8765"))
        avatar_host = os.environ.get("MAIPAI_STACKCHAN_AVATAR_HOST", "127.0.0.1")
        if "MAIPAI_XIAOZHI_HOST" in os.environ and "MAIPAI_STACKCHAN_AVATAR_HOST" not in os.environ:
            avatar_host = host
        avatar_port = int(os.environ.get("MAIPAI_STACKCHAN_AVATAR_PORT", "8766"))
    except ValueError as exc:
        raise ValueError(
            "StackChan listener ports must be TCP port numbers. "
            "Set MAIPAI_XIAOZHI_PORT and MAIPAI_STACKCHAN_AVATAR_PORT to free ports."
        ) from exc
    if link is None or offline is None:
        asyncio.run(
            _serve_stackchan_channels(stop_event, host, xiaozhi_port, avatar_host, avatar_port)
        )
    else:
        asyncio.run(
            _serve_stackchan_channels(
                stop_event, host, xiaozhi_port, avatar_host, avatar_port, link, offline
            )
        )


# FACE-01's own model_id convention (home's lib/biometricPrints.ts's
# KNOWN_MODELS uses the identical string, matching on purpose - a
# print synced from the hub is refused by FaceGallery.add() unless
# this body's own model_id matches what the hub stamped it with).
_FACE_MODEL_ID = "sface-2021dec"

# G4's settings page: the SDK starts a FastAPI server bound to this URL
# only when custom_app_url is set. Port picked from the design-resolver's
# own worked example (2026-09-28) of what a parent would type - no
# stronger convention exists yet across the Reachy Mini app ecosystem.
SETTINGS_APP_URL = "http://127.0.0.1:8042"


def _app_version() -> str | None:
    """The installed `maipai-bot` version, or None when the package is not
    installed (a bare source checkout), which the spec's nullable
    `app_version` says the hub reads as "no version known"."""
    try:
        return importlib.metadata.version("maipai-bot")
    except importlib.metadata.PackageNotFoundError:
        return None


def _data_dir() -> Path:
    default = str(Path.home() / ".local/share/maipai-bot")
    return Path(os.environ.get("MAIPAI_BOT_DATA_DIR") or default)


def _default_pairing_path() -> Path:
    return _data_dir() / "hub-pairing.json"


def _default_models_cache_dir() -> Path:
    return _data_dir() / "models"


_NEUTRAL_POSE = HeadPose()
_NEUTRAL_ANTENNAS = AntennaPositions(left=0.0, right=0.0)
_NEUTRAL_DURATION_S = 1.0
_STOP_POLL_INTERVAL_S = 0.1

_STATE_STARTING = "starting"
_STATE_HOLDING_NEUTRAL = "holding_neutral"
_STATE_BODY_LOST = "body_lost"
_STATE_STOPPED = "stopped"
_STATE_WAITING_FOR_PAIRING = "waiting_for_pairing"
_STATE_CONVERSATION_LOOP = "conversation_loop"


def _sigint_handler(stop_event: threading.Event) -> Callable[[int, object], None]:
    """Return a handler that turns SIGINT into a normal stop_event.set()."""

    def handler(signum: int, frame: object) -> None:
        logger.info("SIGINT received")
        stop_event.set()

    return handler


def _log_state(state: str) -> None:
    logger.info("state: %s", state)


_SLEEP_AFTER_ENV = "MAIPAI_LINK_SLEEP_AFTER_MIN"


def _sleep_after_s(environ: Mapping[str, str] | None = None) -> float:
    """LINK-STATE-01's "after N minutes" setting, from the environment (no
    settings store exists yet). An unreadable or non-positive value falls
    back to the unmeasured default rather than disabling sleep."""
    environ = os.environ if environ is None else environ
    raw = environ.get(_SLEEP_AFTER_ENV)
    if raw is not None:
        try:
            minutes = float(raw)
        except ValueError:
            minutes = math.nan
        if math.isfinite(minutes) and minutes > 0:
            return minutes * 60.0
        logger.warning("ignoring %s=%r; using the default", _SLEEP_AFTER_ENV, raw)
    return DEFAULT_SLEEP_AFTER_MINUTES * 60.0


@dataclass
class LinkStack:
    """The hub link and the offline ladder over it, built together."""

    machine: LinkStateMachine
    link: LinkLifecycle
    offline: OfflineRungs
    supervisor: LinkSupervisor
    announcer: CodeAnnouncer


def _build_link_stack(
    store: PairingStore,
    client: HubLinkClient,
    *,
    discover: DiscoverHub,
    sleep_after_s: float,
    clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
    label: str = "Reachy Mini",
    pairing_secret_path: Path | None = None,
    extra_capabilities: list[str] | None = None,
    hub_url: str | None = None,
) -> LinkStack:
    """LINK-STATE-01's wiring. Rung 1's recognizer and router are left
    unwired: the keyword spotter's cost on the Compute Module is UNVERIFIED
    (docs/dev/offline-ladder-unit-checks.md), so a wake during an outage
    gets the acknowledgement animation and the status line until that row is
    recorded and a recognizer is passed in."""
    machine = LinkStateMachine(clock=clock, wall_clock=wall_clock, sleep_after_s=sleep_after_s)
    # G4b: the pairing code is spoken from the offline clips; the speaker is
    # attached once the body is up (`run_paired_body`).
    announcer = CodeAnnouncer()
    link = LinkLifecycle(
        store,
        client,
        discover=discover,
        observer=machine,
        address_walk=True,
        on_code=announcer,
        label=label,
        pairing_secret_path=pairing_secret_path,
        extra_capabilities=extra_capabilities,
        hub_url=hub_url,
    )
    announcer.current_code = lambda: link.state.code
    rung0 = Rung0Cues(machine=machine, clock=clock)
    offline = OfflineRungs(machine=machine, rung0=rung0, retry_link=link.reconnect_once)
    supervisor = LinkSupervisor(
        machine=machine,
        reconnect=link.reconnect_once,
        clock=clock,
        rung0=rung0,
    )
    return LinkStack(
        machine=machine,
        link=link,
        offline=offline,
        supervisor=supervisor,
        announcer=announcer,
    )


def _knock_hooks(
    offline: OfflineRungs | None,
) -> tuple[Callable[[], bool] | None, Callable[[], None] | None]:
    """KNOCK-01's two hooks: the robot sleeps in the ladder's `sleeping` phase,
    and a double knock is an immediate try at the hub (the supervisor's own
    sleeping cadence is minutes). None while there is no ladder."""
    if offline is None:
        return None, None

    def is_asleep() -> bool:
        return offline.machine.phase is LinkPhase.SLEEPING

    def wake() -> None:
        if offline.retry_link is not None:
            offline.retry_link()

    return is_asleep, wake


def _link_state_payload(link: LinkLifecycle, offline: OfflineRungs) -> dict:
    """The settings page's frame: pairing as before, plus the ladder's phase
    and its rung 2 status text (always visible, whatever can be spoken)."""
    state = link.state
    return {
        "paired": state.paired,
        "code": state.code,
        "hub_instance_id": state.hub_instance_id,
        "link": {
            "phase": offline.machine.phase.value,
            "status": offline.status_text(),
            "reply": offline.last_reply.text if offline.last_reply is not None else None,
        },
    }


def _clip_speaker(cache_dir: Path, playback: AudioPlayback) -> OfflineSpeaker | None:
    """The offline clip speaker, or None while the bundle is not released
    or not rendered (G4b): the ladder then cues the body and shows text."""
    try:
        return OfflineSpeaker(ensure_clip_bundle(cache_dir), playback)
    except (AssetUnavailable, ClipsUnavailable, ManifestError) as exc:
        logger.info("offline clips unavailable, the ladder stays silent: %s", exc)
        return None


def _hold_neutral(client: HeadActuator) -> None:
    """goto neutral, then hold - the floor `run_paired_body` starts
    from every time, whether it ends up waiting for pairing or (once
    paired) running the real conversation loop."""
    client.goto(
        pose=_NEUTRAL_POSE,
        antennas=_NEUTRAL_ANTENNAS,
        body_yaw=0.0,
        duration_s=_NEUTRAL_DURATION_S,
    )
    client.hold()


def _start_eyes() -> Indicator:
    """The Reachy Eyes, or a null indicator when they cannot be started. An
    absent board is not an error: the client reports ``connected=False`` and
    keeps looking; the body runs the same without it."""
    try:
        eyes = EyesClient()
        eyes.start()
        return eyes
    except Exception:
        logger.warning("the Reachy Eyes could not be started; running without them", exc_info=True)
        return NullIndicator()


def _attach_motor_safety(client: ReachyMiniClient, stop_event: threading.Event):
    """SETTLE-GATE and MOTOR-RECOVER-01: every head command goes through the gate,
    the watchdog compares what was asked with where the body is, and the process
    leaves the head at a safe rest when it stops (never asleep)."""
    bus = DaemonMotorBus.for_client(client)
    gate = MotorGate(client, bus)

    def offer(names: list[str]) -> None:
        logger.warning("motors %s are stuck; a reboot is offered and needs a yes", names)

    def repaired(record: dict) -> None:
        logger.warning("motor repair record: %s", record)

    health = MotorHealth(
        bus,
        commanded=lambda: gate.commanded,
        present=client.present_state,
        on_offer=offer,
        on_repair=repaired,
        after_step=gate.invalidate_checks,
    )

    def safe_exit_when_stopped() -> None:
        stop_event.wait()
        try:
            why = gate.safe_exit()
            if why:
                logger.info("safe exit skipped motion: %s", why)
        except Exception:
            logger.warning("safe exit failed", exc_info=True)

    threading.Thread(target=safe_exit_when_stopped, name="motor-safe-exit", daemon=True).start()
    return gate, health


def _attach_eyes(
    client: ReachyMiniClient, stop_event: threading.Event
) -> tuple[LiveCaptureTap, EyesDirector]:
    """EYES-02: the one tap every mic open and frame read goes through, and the
    director that turns its facts and the funnel's shown state into looks.
    Settings and age-band presence have no bot-side transport yet, so the
    tested providers deliberately return defaults and unknown presence."""
    indicator = _start_eyes()
    tap = LiveCaptureTap(client)
    director = EyesDirector(indicator, settings=_eyes_settings, presence=_eyes_presence)
    tap.subscribe(director.on_capture)

    def close_when_stopped() -> None:
        stop_event.wait()
        director.close()
        close = getattr(indicator, "close", None)
        if close is not None:
            close()

    threading.Thread(target=close_when_stopped, name="eyes-close", daemon=True).start()
    return tap, director


# The latest settings frame values the eyes read (their own keys plus the household
# quiet hours); empty until the hub sends any, which parses to the declared defaults.
_EYES_VALUES: dict[str, object] = {}


def _eyes_settings():
    """The eyes' settings from the hub's settings frame; declared defaults before it."""
    from maipai_body.indicator.settings import parse_settings

    return parse_settings(_EYES_VALUES)


def _eyes_presence():
    """Age-band presence is supplied by Home; unknown is the safe interim value."""
    return None


def _build_conversation_loop(
    client: ReachyMiniClient,
    session_cookie: str,
    base_url: str,
    cache_dir: Path,
    link: LinkLifecycle,
    stop_event: threading.Event,
    *,
    offline: OfflineRungs | None = None,
) -> ConversationLoop:
    """Real construction, once paired: everything G9's `ConversationLoop`
    needs, pointed at the paired hub and the local model cache.

    FACE-01's own gap (`docs/BACKLOG.md`): "real `FiveLandmarkDetector`/
    `SFaceEmbedder`/`FaceGallery` construction wherever the daemon
    actually boots the loop (nothing does yet)" - this is that
    wherever. Print sync starts here because this function creates the
    gallery it updates and already owns the live credentials reader.
    Model downloads (the wake-word front end, the
    wake phrase, SFace) happen here, synchronously, the first time a
    fresh install ever reaches a paired state.
    """
    from maipai_body.link.assets import AssetSync

    asset_sync = [AssetSync(base_url, session_cookie)]
    asset_sync[0].sync(cache_dir)
    hub_credentials = _hub_credentials_reader(link, base_url)
    # From here every consumer gets the tap, never the bare client: it is how
    # the green live cue knows when the voice is leaving for the hub.
    gate, motor_health = _attach_motor_safety(client, stop_event)
    tap, director = _attach_eyes(gate, stop_event)
    wakeword_paths = ensure_wakeword_models(cache_dir)
    wake_engine = OpenWakeWordEngine(
        wake_phrase_model=wakeword_paths[WAKE_PHRASE.file],
        melspec_model=wakeword_paths[MELSPECTROGRAM.file],
        embedding_model=wakeword_paths[EMBEDDING.file],
    )
    audio_playback = AudioPlayback(tap)
    if offline is not None:
        offline.speaker = _clip_speaker(cache_dir, audio_playback)
        if offline.rung0 is not None:
            offline.rung0.attach(speaker=offline.speaker)
    gallery = FaceGallery(model_id=_FACE_MODEL_ID, model_sha256=SFACE.sha256)
    print_sync = PrintSync(gallery, hub_credentials, stop_event)
    # FACE-WATCH-01: the always-on watch, at the default `identify` until the
    # hub's settings_changed says otherwise (enrolled faces only: the gallery
    # holds no print for a guest, and each person's own level still applies).
    thermal_monitor = ThermalMonitor()
    vision_watch = VisionWatch(
        tap,
        FiveLandmarkDetector(),
        ensure_embedder(cache_dir),
        gallery,
        # THERMAL-01: the one governor sets the rate (2 Hz from 70 C), not a second thermometer.
        rate_hz=lambda: thermal_monitor.state.vision_hz,
    )
    is_asleep, wake_from_sleep = _knock_hooks(offline)
    offer_engine = _build_offer_engine(cache_dir, os.environ)
    # FOLLOWUP-01: the directory is the seam the hub's roster fills (age band and
    # `person.robot.follow_up` per person; `RosterPoller` below). Until a fetch
    # fills it, and again when it goes stale, every speaker is the child default
    # and the window stays closed, which is the safe direction.
    people = PeopleDirectory()
    follow_up = FollowUpPolicy(people)
    sleep = _build_sleep_auto(tap, vision_watch, os.environ)
    expression_engine = ExpressionEngine(
        tap,
        REACHY_MINI_PROFILE,
        threaded=True,
        speech_rms_provider=audio_playback.recent_rms,
        state_feed_factory=lambda: tap.state_feed(frequency=50.0),
    )
    loop = ConversationLoop(
        client=tap,
        expression_engine=expression_engine,
        attention=_build_attention(expression_engine, os.environ),
        touch_detector=_build_touch_detector(os.environ),
        sleep_auto=sleep.policy if sleep else None,
        luma_source=sleep.luma if sleep else None,
        quiet_hours=sleep.quiet.active if sleep else None,
        audio_capture=AudioCapture(tap),
        audio_playback=audio_playback,
        wake_scorer=WakeScorer(wake_engine, tap),
        stt_client=SttStreamClient(base_url, session_cookie),
        turn_client=TurnClient(base_url, session_cookie),
        tts_client=TtsPlaybackClient(base_url, session_cookie, audio_playback),
        hub_credentials=hub_credentials,
        vision_watch=vision_watch,
        follow_up=follow_up,
        offline=offline,
        # MOVES-01: None unless MAIPAI_BOT_REACT_MOVES is set.
        react_hook=build_react_hook(tap, cache_dir / "moves", os.environ),
        carry_gravity_compensation=REACHY_MINI_PROFILE.carry_gravity_compensation,
        capture_scope=tap.sending_to_hub,
        motor_health=motor_health,
        thermal=thermal_monitor,
        is_asleep=is_asleep,
        wake_from_sleep=wake_from_sleep,
        offer_engine=offer_engine,
        unmute_listener=_build_unmute_listener(cache_dir, os.environ),
        band_of=people.band_of,
        presence_entries=lambda: presence_entries_from(vision_watch.current(), people.band_of),
    )
    loop.subscribe_view(director.on_view)
    alarm = _build_alarm_controller(loop, audio_playback, offline, people, lambda m: _send(m))
    loop.set_alarm_word_handler(alarm.on_spoken)
    threading.Thread(
        target=_alarm_backstop, args=(alarm, stop_event), name="alarm-backstop", daemon=True
    ).start()
    threading.Thread(target=print_sync.run, name="face-print-sync", daemon=True).start()
    # FOLLOWUP-01: the hub's roster fills `people` (refresh now, every 30 s, and
    # right after a command-channel drop); a stale roster clears to unknown.
    roster_poller = RosterPoller(people, hub_credentials, stop_event)
    threading.Thread(target=roster_poller.run, name="roster-poller", daemon=True).start()

    from maipai_body.link.channel import CommandChannel

    def set_muted(payload: dict) -> dict:
        muted = payload.get("muted")
        if not isinstance(muted, bool):
            raise ValueError("mute command requires a boolean muted field")
        loop.set_muted(muted)
        return {"muted": muted}

    def refresh_assets(_payload: dict) -> None:
        cookie, current_url = hub_credentials()
        refreshed = AssetSync(current_url, cookie)
        refreshed.on_asset_changed(cache_dir)
        asset_sync[0] = refreshed

    def command_credentials() -> tuple[str, str]:
        cookie, current_url = hub_credentials()
        return current_url, cookie

    def apply_settings(payload: dict) -> None:
        values = payload.get("values")
        level = values.get("robot.camera.watch_level") if isinstance(values, dict) else None
        if level in ("off", "presence", "identify"):
            loop.set_watch_level(level)
        if isinstance(values, dict):
            _EYES_VALUES.update(values)
            alarm.apply_settings(values)
        if sleep is not None and isinstance(values, dict):
            sleep.apply_settings(values)
        seconds = values.get("robot.follow_up.seconds") if isinstance(values, dict) else None
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
            follow_up.set_seconds(seconds)

    command_channel = CommandChannel(
        base_url,
        session_cookie,
        credentials=command_credentials,
        settings_handler=apply_settings,
        time_handler=getattr(getattr(link.hub_client, "clock_sync", None), "observe_iso", None),
        on_drop=link.channel_lost,
        handlers={
            "mute": lambda _payload: set_muted({"muted": True}),
            "unmute": lambda _payload: set_muted({"muted": False}),
            "asset_changed": refresh_assets,
            "motor_reboot": motor_reboot_handler(loop),
            "offer": loop.offer.receive,
            "alarm": alarm.handle_command,
        },
    )
    loop.bind_offer_frames(command_channel.send_frame)

    def _send(message: dict) -> bool:
        return command_channel.send_frame(message)

    from maipai_body.vision.live_view import LiveViewStreamer

    def post_live_frame(view_id: str, jpeg: bytes) -> int:
        import requests

        cookie, current_url = hub_credentials()
        response = requests.post(
            f"{current_url.rstrip('/')}/api/devices/me/stream/{view_id}",
            data=jpeg,
            headers={"Cookie": f"session={cookie}", "Content-Type": "image/jpeg"},
            timeout=(3, 5),
        )
        return response.status_code

    live_view = LiveViewStreamer(
        camera=tap,
        post_frame=post_live_frame,
        refusal=loop.live_view_refusal,
        connected=lambda: command_channel.connected,
    )
    command_channel.handlers["live_view_start"] = live_view.start
    command_channel.handlers["live_view_stop"] = live_view.stop
    command_channel.add_drop_listener(live_view.on_channel_drop)
    command_channel.add_drop_listener(roster_poller.poke)
    threading.Thread(
        target=command_channel.run,
        args=(stop_event,),
        name="robot-command-channel",
        daemon=True,
    ).start()
    return loop


def motor_reboot_handler(loop: Any) -> Callable[[dict], dict]:
    """The hub's `motor_reboot` (spec-v0.1.151): sent only after an adult said yes on the
    Devices card, and it reboots only the motors named. The ack carries the outcome and
    the next state frame shows what is still latched."""

    def handle(payload: dict) -> dict:
        motors = payload.get("motors")
        if (
            not isinstance(motors, list)
            or not motors
            or not all(isinstance(name, str) and name for name in motors)
        ):
            raise ValueError("motor_reboot requires a non-empty motors list of names")
        return loop.reboot_motors(motors)

    return handle


def _build_attention(engine: ExpressionEngine, env: Mapping[str, str]) -> object | None:
    """S-EXPR-04: our own gaze and idle layers instead of the daemon's tracker.
    Off unless MAIPAI_BOT_ATTENTION=1: every number in it is an UNMEASURED design
    default until the unit rows (M-R2) confirm them, so the daemon tracker stays
    the default."""
    if env.get("MAIPAI_BOT_ATTENTION") != "1":
        return None
    from maipai_body.presence.attention import Attention

    return Attention(engine, clock=time.monotonic)


@dataclass
class _SleepAuto:
    """SLEEP-AUTO-01's pieces, so `apply_settings` can reach the live policy."""

    policy: object
    luma: Callable[[], float | None]
    quiet: object

    def apply_settings(self, values: Mapping[str, object]) -> None:
        self.quiet.apply(values)  # type: ignore[attr-defined]
        auto = values.get("robot.sleep.auto")
        if isinstance(auto, bool):
            self.policy.auto_enabled = auto  # type: ignore[attr-defined]


def _build_sleep_auto(camera: object, vision_watch: VisionWatch, env: Mapping[str, str]):
    """SLEEP-AUTO-01: dark-and-quiet and quiet-hours sleep. Off unless
    MAIPAI_BOT_SLEEP_AUTO=1 (its thresholds are UNMEASURED). `robot.sleep.auto` and
    `household.quiet_hours.from`/`.to` are registry keys since spec-v0.1.151; the
    registry default for the first is on, so the policy starts enabled and a
    `settings_changed` only ever turns it off or back on."""
    if env.get("MAIPAI_BOT_SLEEP_AUTO") != "1":
        return None
    from maipai_body.presence.sleep_auto import QuietHours, SleepAutoPolicy, luma_reader

    return _SleepAuto(
        policy=SleepAutoPolicy(auto_enabled=True),
        luma=luma_reader(camera, level=lambda: vision_watch.device_level),
        quiet=QuietHours(),
    )


def _build_touch_detector(env: Mapping[str, str]) -> object | None:
    """TOUCH-01: an antenna push acknowledges, or wakes a sleeping robot. Off unless
    MAIPAI_BOT_TOUCH=1: the thresholds are UNMEASURED until runbook rows T0 to T4."""
    if env.get("MAIPAI_BOT_TOUCH") != "1":
        return None
    from maipai_body.presence.touch import AntennaTouchDetector

    return AntennaTouchDetector()


def _build_offer_engine(cache_dir: Path, env) -> object | None:
    """OFFER-01: the local spotter for the offer window, or None (offers are then
    refused with `no_spotter`). Off unless MAIPAI_BOT_OFFER_SPOTTER=1: the offer
    phrases' token file is not yet checked against the pinned model."""
    if env.get("MAIPAI_BOT_OFFER_SPOTTER") != "1":
        return None
    try:
        from maipai_body.speech.kws import (
            OFFER_KEYWORDS_FILE,
            SherpaKeywordEngine,
            ensure_kws_model,
        )

        return SherpaKeywordEngine(ensure_kws_model(cache_dir), keywords_file=OFFER_KEYWORDS_FILE)
    except Exception:
        logger.warning("offer spotter unavailable; offers will be refused", exc_info=True)
        return None


def _build_unmute_listener(cache_dir: Path, env) -> object | None:
    """MUTE-LOCAL-01: the on-robot "listen again" spotter, or None (a hub mute can then
    only be lifted by the hub). Off unless MAIPAI_BOT_UNMUTE_SPOTTER=1: the phrase's
    token file is hand-tokenised and its CPU row is not measured."""
    if env.get("MAIPAI_BOT_UNMUTE_SPOTTER") != "1":
        return None
    try:
        from maipai_body.speech.kws import (
            UNMUTE_KEYWORDS_FILE,
            SherpaKeywordEngine,
            UnmuteListener,
            ensure_kws_model,
        )

        engine = SherpaKeywordEngine(
            ensure_kws_model(cache_dir), keywords_file=UNMUTE_KEYWORDS_FILE
        )
        return UnmuteListener(engine)
    except Exception:
        logger.warning("unmute spotter unavailable; only the hub can unmute", exc_info=True)
        return None


class _AlarmSpeaker:
    """The alarm's `AlarmPlayer`: a fixed chime and bundle clips through the
    robot's own playback. It never synthesises; no bundle means chime only."""

    def __init__(self, playback: AudioPlayback, offline: OfflineRungs | None) -> None:
        self._playback = playback
        self._offline = offline

    def _speaker(self):
        return None if self._offline is None else self._offline.speaker

    def chime(self) -> None:
        rate = self._playback.output_samplerate()
        if rate:
            self._playback.push(chime_samples(rate))

    def clips(self, clip_ids) -> bool:
        speaker = self._speaker()
        if speaker is None or not speaker.can_say(list(clip_ids)):
            return False
        return bool(speaker.say(list(clip_ids)))

    def stop(self) -> None:
        self._playback.flush()


def _build_alarm_controller(
    loop: ConversationLoop,
    playback: AudioPlayback,
    offline: OfflineRungs | None,
    people: PeopleDirectory,
    send: Callable[[dict], bool],
) -> AlarmController:
    """ALARM-PLAY-01. No daemon volume seam exists on this body yet, so the
    floor is applied only where a `Volume` is injected (BACKLOG, open)."""
    from maipai_body.speaker_evidence import effective_band

    def bundle():
        speaker = None if offline is None else offline.speaker
        return getattr(speaker, "bundle", None)

    def has(clip_id: str) -> bool:
        b = bundle()
        return b is not None and b.has(clip_id)

    def resolve(kind, area):
        b = bundle()
        return [] if b is None else alarm_clip_ids(b.manifest, has, kind, area)

    return AlarmController(
        player=_AlarmSpeaker(playback, offline),
        present=loop.set_safety_alarm,
        resolve_clips=resolve,
        child_clips=lambda: alarm_child_clip_ids(has),
        send_action=send,
        audience=lambda: loop.speaker_snapshot()[1],
        is_child=lambda entry: effective_band(entry, people.band_of)[0] == "child",
        evidence=lambda: loop.speaker_snapshot()[0],
    )


def _alarm_backstop(alarm: AlarmController, stop_event: threading.Event) -> None:
    while not stop_event.wait(1.0):
        try:
            alarm.tick()
        except Exception:
            logger.warning("alarm backstop failed", exc_info=True)


def _light_from_last_look(vision: Any, lux: float | None = None) -> str | None:
    """Dark, dim or bright from the newest camera frame (kept in memory for the next post)."""
    if vision is None:
        return None
    from maipai_body.bodies.stackchan.vision_post import light_bucket

    look = vision.latest_look(max_age_s=60.0)
    return light_bucket(look[2], lux) if look is not None else light_bucket(None, lux)


def _wire_orientation(voice: Any, behavior: Any, bridge: Any, night: Any, power: Any) -> None:
    """Pose faces, lines, screen rotation and the motion hold for the unit's orientation events."""
    from maipai_body.bodies.stackchan.orientation import (
        SCREEN_ROTATION_ENABLED,
        OrientationReactions,
    )

    def rotate(degrees: int) -> None:
        if not SCREEN_ROTATION_ENABLED:
            return
        try:
            voice.robot.client._call("self.screen.set_rotation", {"degrees": degrees})
        except Exception:
            behavior._warn_limited("rotation", "StackChan screen rotation failed")

    def asleep() -> bool:
        return behavior._rest.stage != "awake"

    orientation = OrientationReactions(
        face=lambda expression: behavior.show_face(expression, while_listening=False),
        say=bridge.speak_reaction,
        rotate=rotate,
        hold_motion=power.set_orientation_hold,
        quiet=lambda: ("night mode is on" if night.night else "") or ("asleep" if asleep() else ""),
        busy=behavior.reaction_blocked,
    )
    behavior.orientation = orientation
    night.sensors_blocked = orientation.sensors_untrusted
    behavior.pose_held = lambda: orientation.pose != "upright"

    def tick() -> None:
        orientation.tick()

    behavior.orientation_tick = tick
    voice.session_listeners.append(lambda _device_id: orientation.reassert())
    bridge.on_turn_end = orientation.on_turn_end


def _start_robot_checkin(voice: Any, behavior: Any, link: LinkLifecycle, stop_event: Any) -> None:
    """Report the connected StackChan to the hub: address, firmware, memory, boot reason."""
    from maipai_body.link.checkin import RobotCheckin, UnitFacts, build_payload

    facts = UnitFacts()
    behavior.unit_facts = facts
    connected = threading.Event()
    voice.session_listeners.append(lambda _device_id: connected.set())

    def collect() -> dict[str, Any]:
        sessions = list(voice._sessions)
        device_id = sessions[0] if sessions else None
        address, since = voice._session_info.get(device_id, (None, None))
        status: dict[str, Any] = {}
        if device_id is not None:
            try:
                status = {
                    "network": (voice.robot.client.get_device_status() or {}).get("network"),
                    "battery": voice.robot.client.get_battery_status(),
                }
                battery = status["battery"]
                status["battery"] = {
                    "level": battery.get("percent"),
                    "charging": battery.get("charging"),
                }
            except Exception:
                logger.debug("robot check-in could not read the unit's status", exc_info=True)
        return build_payload(
            device_id=device_id,
            address=address,
            connected_since=since,
            facts=facts.snapshot(),
            orientation=getattr(behavior.orientation, "pose", None),
            status=status,
            bot_version=_app_version(),
            now=time.time(),
        )

    reporter = RobotCheckin(
        _hub_credentials_reader(link, ""), stop_event, collect, facts, connected
    )
    threading.Thread(target=reporter.run, name="robot-checkin", daemon=True).start()


def _hub_credentials_reader(link: LinkLifecycle, base_url: str) -> Callable[[], tuple[str, str]]:
    """Build a live credentials reader that retains the last good URL."""
    last_known_good_url = [base_url]

    def read() -> tuple[str, str]:
        try:
            pairing = link.pairing_store.load()
        except Exception:
            logger.warning("failed to read hub pairing during credential refresh", exc_info=True)
        else:
            if pairing is not None:
                last_known_good_url[0] = pairing.base_url
        # The address that last answered wins over the stored one: a tailnet
        # answer is not persisted (the LAN address stays the pairing) but the
        # turn clients must still reach the hub where it answered.
        answered = getattr(link.hub_client, "active_base_url", None)
        return link.hub_client.session_cookie or "", answered or last_known_good_url[0]

    return read


def _load_yunet_model(link: LinkLifecycle | None) -> Path:
    """The verified YuNet file: from the local model cache, else synced from the paired hub."""
    from maipai_body.link.assets import AssetSync
    from maipai_body.model_assets import AssetUnavailable, ensure_asset
    from maipai_body.vision.models import YUNET

    cache = _default_models_cache_dir()
    try:
        return ensure_asset(YUNET, cache)  # already synced (or the fetcher is configured)
    except AssetUnavailable:
        pass
    if link is None:
        raise AssetUnavailable("YuNet is not synced and the robot is not paired with Home")
    url, cookie = _command_credentials(link)()
    if not url or not cookie:
        raise AssetUnavailable("YuNet is not synced and Home has not answered yet")
    sync = AssetSync(url, cookie, refresh_credentials=_command_credentials(link))
    return sync.ensure(YUNET, cache)


def _effective_idle_level(level: str) -> str:
    """The idle level acted on: Home's default "calm" counts as "still"."""
    return "still" if level == "calm" else level


def _command_credentials(link: LinkLifecycle) -> Callable[[], tuple[str, str]]:
    """The command channel's reader: ``(base_url, session_cookie)``, in that order.

    ``_hub_credentials_reader`` answers ``(cookie, url)``; the channel unpacks the other way, so
    the cookie was used as the URL and the channel failed with a ValueError every 30 s.
    """
    read = _hub_credentials_reader(link, "")

    def credentials() -> tuple[str, str]:
        cookie, url = read()
        return url, cookie

    return credentials


def _has_stored_pairing(link: LinkLifecycle) -> bool:
    try:
        return link.pairing_store.load() is not None
    except Exception:
        logger.warning("could not read the stored pairing at boot", exc_info=True)
        return False


def _clock_synced(link: object) -> bool:
    """ROBOT-TIME-01: false until the first contact with the hub since boot."""
    sync = getattr(getattr(link, "hub_client", None), "clock_sync", None)
    return bool(getattr(sync, "synced", False)) if isinstance(sync, ClockSync) else False


def run_paired_body(
    client: ReachyMiniClient,
    link: LinkLifecycle,
    stop_event: threading.Event,
    *,
    cache_dir: Path,
    offline: OfflineRungs | None = None,
    supervisor: LinkSupervisor | None = None,
    announcer: CodeAnnouncer | None = None,
) -> None:
    """The real boot path: hold neutral until G4's link reports paired,
    then hand off to `ConversationLoop` for the rest of the process's
    life. Still holds neutral and honors `stop_event`/SIGINT within one
    second if pairing never happens - RM-03's own original scaffold
    contract, unchanged.

    Hub-facing speech clients are refreshed at turn boundaries from
    the link's live session cookie and pairing URL, so an in-flight
    turn keeps its original clients while the next turn picks up a
    rotated session.
    """
    _log_state(_STATE_STARTING)
    try:
        _hold_neutral(client)
        _log_state(_STATE_HOLDING_NEUTRAL)
        _log_state(_STATE_WAITING_FOR_PAIRING)
        if announcer is not None:
            # An unpaired robot has no hub to synthesize the code with: it
            # says it from the clips, so the speaker exists before pairing.
            threading.Thread(
                target=lambda: announcer.attach(_clip_speaker(cache_dir, AudioPlayback(client))),
                name="pairing-code-speaker",
                daemon=True,
            ).start()
        # A body that was paired before does not wait for the hub: the ladder
        # and the wake behavior run from boot, whether or not the first
        # redeem has succeeded (LINK-STATE-01). A body never paired still
        # waits for pairing, as before.
        boot_offline = offline is not None and _has_stored_pairing(link)
        paired = False
        while not stop_event.is_set():
            if link.state.paired or boot_offline:
                paired = True
                break
            stop_event.wait(_STOP_POLL_INTERVAL_S)
        if not paired:
            return

        if boot_offline:
            # The machine starts connected; with a stored pairing and no
            # redeem yet that is not true, so the outage state, the supervisor's
            # retries and the wake's offline path start now, not when the first
            # redeem finally fails (its walk can take many seconds).
            offline.machine.booted_without_contact("the hub has not answered since power-on")

        if supervisor is not None:
            threading.Thread(
                target=supervisor.run, args=(stop_event,), name="link-supervisor", daemon=True
            ).start()

        pairing = link.pairing_store.load()
        if pairing is None:
            # Paired per LinkLifecycle's in-memory state but the file
            # it just wrote is unreadable - report as body_lost's own
            # sibling rather than crash the process on a torn write.
            logger.error("link reports paired but the pairing record could not be read")
            return
        session_cookie = link.hub_client.session_cookie
        if not session_cookie and boot_offline:
            # The hub has not answered yet. The loop re-reads the live cookie
            # at its first turn boundary, so an empty one here is never used.
            session_cookie = ""
        elif not session_cookie:
            # Same shape as the unreadable-pairing-record case above: a
            # code review (2026-09-28) caught this silently falling
            # back to "" and building every hub client anyway, which
            # would only surface as an opaque 401 deep inside the first
            # real turn instead of a clear error right here.
            logger.error("link reports paired but has no session cookie")
            return

        hub_credentials = _hub_credentials_reader(link, pairing.base_url)
        loop_ready = threading.Event()
        loop_result: list[ConversationLoop] = []

        def state_snapshot() -> dict[str, object]:
            # `daemon_version` is the vendor SDK's version; `app_version`
            # is this app's own (`maipai-bot`), the one the hub compares
            # to a getmaipai/bot release (ROBOT-STATE-SPEC-02, G10-VERSION).
            versions = {
                "daemon_version": getattr(reachy_mini, "__version__", None),
                "app_version": _app_version(),
            }
            if not loop_ready.is_set() or not loop_result:
                return {
                    "activity": "starting",
                    "muted": False,
                    "tracking": False,
                    "clock_synced": _clock_synced(link),
                    "on_battery": None,
                    "battery_level": None,
                    **versions,
                }
            return {
                **loop_result[0].snapshot(),
                "clock_synced": _clock_synced(link),
                "on_battery": None,
                "battery_level": None,
                **versions,
            }

        state_change_event = threading.Event()
        state_change_event.set()
        reporter = StateReporter(
            hub_credentials,
            stop_event,
            state_snapshot,
            state_change_event,
        )
        threading.Thread(target=reporter.run, name="robot-state-reporter", daemon=True).start()

        build_result: list[ConversationLoop | Exception] = []

        def build_loop() -> None:
            try:
                # Only passed when there is a ladder, so a body without one
                # builds the loop exactly as before.
                extra = {"offline": offline} if offline is not None else {}
                loop = _build_conversation_loop(
                    client, session_cookie, pairing.base_url, cache_dir, link, stop_event, **extra
                )
                loop_result.append(loop)
                loop_ready.set()
                state_change_event.set()
                build_result.append(loop)
            except Exception as exc:
                build_result.append(exc)

        try:
            build_thread = threading.Thread(
                target=build_loop, name="conversation-loop-build", daemon=True
            )
            build_thread.start()
            while build_thread.is_alive():
                if stop_event.wait(_STOP_POLL_INTERVAL_S):
                    logger.info(
                        "stop requested during model download; abandoning conversation loop build"
                    )
                    return
            build_thread.join()
            if isinstance(build_result[0], Exception):
                raise build_result[0]
            loop = build_result[0]
        except Exception:
            # A code review (2026-09-28) caught this uncaught: a
            # model-download failure (no network, GitHub briefly
            # unreachable, a corrupted partial download tripping
            # model_assets.py's checksum check) is a plain RuntimeError
            # subclass, not BodyLost, so it used to propagate out of
            # this function and crash the whole daemon process - on
            # every restart, for a fresh install with a flaky network,
            # until someone noticed and intervened by hand. Logged and
            # treated as "couldn't reach conversational state," the
            # same as the two branches above, not a crash.
            logger.exception("failed to build the conversation loop")
            return
        _log_state(_STATE_CONVERSATION_LOOP)
        loop.run(stop_event)
    except BodyLost:
        _log_state(_STATE_BODY_LOST)
    finally:
        _log_state(_STATE_STOPPED)


def _clock_setter(hosted: bool):
    """A hosted body (StackChan) never sets its host computer's clock and never runs sudo."""
    return None if hosted else system_clock_setter()


class MaiPaiBody(ReachyMiniApp):
    """The MaiPai body, run by the daemon as its one app."""

    custom_app_url: str | None = SETTINGS_APP_URL

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        store = PairingStore(_default_pairing_path())
        hosted = os.environ.get("MAIPAI_HUB_HOST") == "1"
        from maipai_body.logging_setup import configure_logging

        configure_logging(hosted)
        discover = _no_hub_discovery if hosted else discover_hub
        self._stack = _build_link_stack(
            store,
            HubLinkClient(
                store,
                clock_sync=ClockSync(_clock_setter(hosted)),
                discover=discover,
            ),
            discover=discover,
            sleep_after_s=_sleep_after_s(),
            label=os.environ.get("MAIPAI_BOT_LABEL", "StackChan" if hosted else "Reachy Mini"),
            pairing_secret_path=(Path(os.environ["MAIPAI_BOT_DATA_DIR"]) / "pairing-secret")
            if hosted
            else None,
            extra_capabilities=["no_vendor_login"] if hosted else [],
            hub_url=os.environ.get("MAIPAI_HUB_URL") if hosted else None,
        )
        self.link = self._stack.link
        # The base class only wires static files + index.html; the
        # settings page's own JS polls this for live pairing state.
        if self.settings_app is not None:

            @self.settings_app.get("/api/state")
            async def link_state() -> dict:
                return _link_state_payload(self.link, self._stack.offline)

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        """Run the body: install the SIGINT handler, start the hub link
        on its own thread, then hold neutral until paired and run the
        real conversation loop for the rest of the process's life."""
        previous_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _sigint_handler(stop_event))
        if _stackchan_selected():
            link_thread = threading.Thread(
                target=self.link.run, args=(stop_event,), name="hub-link", daemon=True
            )
            link_thread.start()
            supervisor_thread = threading.Thread(
                target=self._stack.supervisor.run,
                args=(stop_event,),
                name="link-supervisor",
                daemon=True,
            )
            supervisor_thread.start()
            try:
                _run_stackchan_service(stop_event, self.link, self._stack.offline)
            finally:
                link_thread.join(timeout=5.0)
                signal.signal(signal.SIGINT, previous_handler)
            return
        link_thread = threading.Thread(
            target=self.link.run, args=(stop_event,), name="hub-link", daemon=True
        )
        link_thread.start()
        try:
            client = ReachyMiniClient(REACHY_MINI_PROFILE, reachy=reachy_mini)
            run_paired_body(
                client,
                self.link,
                stop_event,
                cache_dir=_default_models_cache_dir(),
                offline=self._stack.offline,
                supervisor=self._stack.supervisor,
                announcer=self._stack.announcer,
            )
        finally:
            signal.signal(signal.SIGINT, previous_handler)
            link_thread.join(timeout=5.0)


if __name__ == "__main__":
    # The daemon starts an installed app by running its entry point's
    # module as `python -m <module>` in its own subprocess (never by
    # importing the class directly), so this block is the actual thing
    # that runs: found live, RM-03's first daemon-driven start finished
    # in under a second with no error because this block was missing
    # and `python -m maipai_body.app` had nothing to do.
    app = MaiPaiBody()
    try:
        app.wrapped_run()
    except KeyboardInterrupt:
        app.stop()
