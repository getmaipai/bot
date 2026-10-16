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

import reachy_mini
from reachy_mini import ReachyMini, ReachyMiniApp

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.eyes_client import EyesClient
from maipai_body.bodies.reachy_mini.motors import DaemonMotorBus, MotorGate
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.expression.suppression import SuppressionContext
from maipai_body.hal.errors import BodyLost
from maipai_body.hal.seam import AntennaPositions, HeadActuator, HeadPose, Indicator, NullIndicator
from maipai_body.indicator.director import EyesDirector
from maipai_body.indicator.live import LiveCaptureTap
from maipai_body.link import HubLinkClient, PairingStore, discover_hub
from maipai_body.link.discovery import DiscoverHub
from maipai_body.link.lifecycle import LinkLifecycle
from maipai_body.link.offline import OfflineRungs
from maipai_body.link.prints import PrintSync
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
from maipai_body.presence.motor_health import MotorHealth
from maipai_body.presence.thermal import ThermalMonitor
from maipai_body.run_loop import ConversationLoop
from maipai_body.speech.capture import AudioCapture
from maipai_body.speech.models import EMBEDDING, MELSPECTROGRAM, WAKE_PHRASE, ensure_wakeword_models
from maipai_body.speech.offline_clips import (
    AssetUnavailable,
    ClipsUnavailable,
    CodeAnnouncer,
    ManifestError,
    OfflineSpeaker,
    ensure_clip_bundle,
)
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.stt_stream import SttStreamClient
from maipai_body.speech.tts_playback import TtsPlaybackClient
from maipai_body.speech.turn_client import TurnClient
from maipai_body.speech.wake import OpenWakeWordEngine, WakeScorer
from maipai_body.vision.detect import FiveLandmarkDetector
from maipai_body.vision.embed import ensure_embedder
from maipai_body.vision.gallery import FaceGallery
from maipai_body.vision.models import SFACE
from maipai_body.vision.watch import VisionWatch, read_cpu_temp_c

logger = logging.getLogger("maipai_body.app")


def _stackchan_selected(environ: Mapping[str, str] | None = None) -> bool:
    """Whether this Bot process is configured to serve a StackChan body."""
    environ = os.environ if environ is None else environ
    return environ.get("MAIPAI_BODY", "reachy_mini").strip().lower() in {"stackchan", "fake"}


class StackChanBehavior:
    """Shared expression and bounded anonymous tracking for an attached StackChan."""

    def __init__(self, robot, *, vision_bridge=None, idle_interval_s: float = 8.0) -> None:
        from maipai_body.bodies.stackchan.profile import STACKCHAN_PROFILE
        from maipai_body.expression.engine import ExpressionEngine

        self.robot = robot
        self._holder = "stackchan-runtime"
        self._lock = threading.RLock()
        self._active = threading.Event()
        self._closed = threading.Event()
        self._presence_stop: threading.Event | None = None
        self._presence_thread: threading.Thread | None = None
        self._vision = vision_bridge
        self._idle_interval_s = idle_interval_s
        self._last_idle = 0.0
        self._expression = ExpressionEngine(robot._driver("head"), STACKCHAN_PROFILE)

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

    def render_primitive(self, primitive: str) -> bool:
        return self._with_lease(
            lambda: self._expression.render_ambient(primitive, SuppressionContext())
        )

    def render_turn_state(self, state: str, *, mood: str | None = None) -> None:
        self._active.set()
        primitive = {
            "listening": "glance",
            "thinking": "attend",
            "speaking": "speak",
        }.get(state)

        def render() -> None:
            if state == "settle":
                self._expression.render_ambient("settle", SuppressionContext())
                return
            self._expression.render_turn_state(state, mood=mood)
            if primitive is not None:
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
            self.robot.camera.stream(enabled=True)
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
            if not self._active.is_set() and now - self._last_idle >= self._idle_interval_s:
                self._last_idle = now
                try:
                    self.render_primitive("settle")
                except Exception:
                    logger.warning("StackChan idle expression failed", exc_info=True)
            if self._vision is not None and not self._active.is_set():
                try:
                    target = self._vision.track_stream_frame(deadline_s=0.4)
                    if target.detected:
                        self.render_primitive("attend")
                except Exception:
                    logger.warning("StackChan anonymous tracking failed", exc_info=True)

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
        vision_port = int(os.environ.get("MAIPAI_VISION_PORT", "8766"))
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
    vision = None
    try:
        from maipai_body.bodies.stackchan.vision_bridge import StackChanVisionBridge

        vision = StackChanVisionBridge(
            voice.robot.robot,
            detector=FiveLandmarkDetector(),
            embedder=None,
            gallery=None,
        )
    except Exception:
        logger.warning("StackChan anonymous tracking is unavailable", exc_info=True)
    behavior = StackChanBehavior(voice.robot.robot, vision_bridge=vision)
    if link is not None and offline is not None:
        bridge = StackChanTurnBridge(
            voice,
            link,
            offline,
            cache_dir=_default_models_cache_dir(),
            # The current /api/stt/stream contract has no speaker field.
            # This adapter consumes that field when the hub adds it; absent
            # results remain anonymous on this turn.
            person_attribution=lambda result: getattr(result, "speaker_evidence", None),
            expression_sink=behavior.render_turn_state,
        )
        voice.audio_handler = bridge.on_audio
        voice.turn_handler = bridge.listen
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
            behavior.start_presence(stop_event)
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
    except ValueError as exc:
        raise ValueError(
            "StackChan listener ports must be TCP port numbers. "
            "Set MAIPAI_XIAOZHI_PORT and MAIPAI_STACKCHAN_AVATAR_PORT to free ports."
        ) from exc


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


def _eyes_settings():
    """Until the hello settings transport exists, use declared defaults."""
    from maipai_body.indicator.settings import IndicatorSettings

    return IndicatorSettings()


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
    vision_watch = VisionWatch(
        tap,
        FiveLandmarkDetector(),
        ensure_embedder(cache_dir),
        gallery,
        temperature=read_cpu_temp_c,
    )
    is_asleep, wake_from_sleep = _knock_hooks(offline)
    loop = ConversationLoop(
        client=tap,
        expression_engine=ExpressionEngine(
            tap,
            REACHY_MINI_PROFILE,
            threaded=True,
            speech_rms_provider=audio_playback.recent_rms,
            state_feed_factory=lambda: tap.state_feed(frequency=50.0),
        ),
        audio_capture=AudioCapture(tap),
        audio_playback=audio_playback,
        wake_scorer=WakeScorer(wake_engine, tap),
        stt_client=SttStreamClient(base_url, session_cookie),
        turn_client=TurnClient(base_url, session_cookie),
        tts_client=TtsPlaybackClient(base_url, session_cookie, audio_playback),
        hub_credentials=hub_credentials,
        vision_watch=vision_watch,
        offline=offline,
        # MOVES-01: None unless MAIPAI_BOT_REACT_MOVES is set.
        react_hook=build_react_hook(tap, cache_dir / "moves", os.environ),
        carry_gravity_compensation=REACHY_MINI_PROFILE.carry_gravity_compensation,
        capture_scope=tap.sending_to_hub,
        motor_health=motor_health,
        thermal=ThermalMonitor(),

        is_asleep=is_asleep,
        wake_from_sleep=wake_from_sleep,
    )
    loop.subscribe_view(director.on_view)
    threading.Thread(target=print_sync.run, name="face-print-sync", daemon=True).start()

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
        },
    )
    threading.Thread(
        target=command_channel.run,
        args=(stop_event,),
        name="robot-command-channel",
        daemon=True,
    ).start()
    return loop


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


class MaiPaiBody(ReachyMiniApp):
    """The MaiPai body, run by the daemon as its one app."""

    custom_app_url: str | None = SETTINGS_APP_URL

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        store = PairingStore(_default_pairing_path())
        self._stack = _build_link_stack(
            store,
            HubLinkClient(store, clock_sync=ClockSync(system_clock_setter())),
            discover=discover_hub,
            sleep_after_s=_sleep_after_s(),
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
