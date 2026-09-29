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

import logging
import os
import signal
import threading
from collections.abc import Callable
from pathlib import Path

from reachy_mini import ReachyMini, ReachyMiniApp

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.hal.errors import BodyLost
from maipai_body.hal.seam import AntennaPositions, HeadActuator, HeadPose
from maipai_body.link import HubLinkClient, PairingStore, discover_hub
from maipai_body.link.lifecycle import LinkLifecycle
from maipai_body.run_loop import ConversationLoop
from maipai_body.speech.capture import AudioCapture
from maipai_body.speech.models import EMBEDDING, MELSPECTROGRAM, WAKE_PHRASE, ensure_wakeword_models
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.stt_stream import SttStreamClient
from maipai_body.speech.tts_playback import TtsPlaybackClient
from maipai_body.speech.turn_client import TurnClient
from maipai_body.speech.wake import OpenWakeWordEngine, WakeScorer
from maipai_body.vision.detect import FiveLandmarkDetector
from maipai_body.vision.embed import ensure_embedder
from maipai_body.vision.gallery import FaceGallery
from maipai_body.vision.models import SFACE

logger = logging.getLogger("maipai_body.app")

# FACE-01's own model_id convention (home's lib/biometricPrints.ts's
# KNOWN_MODELS uses the identical string, matching on purpose - a
# print synced from the hub is refused by FaceGallery.add() unless
# this body's own model_id matches what the hub stamped it with).
_FACE_MODEL_ID = "sface-2021dec"

# G4's settings page: the SDK starts a FastAPI server bound to this URL
# only when custom_app_url is set. Port picked from the design-resolver's
# own worked example (2026-09-28) of what a parent would type - no
# stronger convention exists yet across the Reachy Mini app ecosystem.
SETTINGS_APP_URL = "http://0.0.0.0:8042"


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


def _build_conversation_loop(
    client: ReachyMiniClient,
    session_cookie: str,
    base_url: str,
    cache_dir: Path,
    link: LinkLifecycle,
) -> ConversationLoop:
    """Real construction, once paired: everything G9's `ConversationLoop`
    needs, pointed at the paired hub and the local model cache.

    FACE-01's own gap (`docs/BACKLOG.md`): "real `FiveLandmarkDetector`/
    `SFaceEmbedder`/`FaceGallery` construction wherever the daemon
    actually boots the loop (nothing does yet)" - this is that
    wherever. The face gallery starts empty: no print-sync mechanism
    exists yet (that's `home`'s own BACKLOG item), so every check
    reports "unknown" until one does - the honest state, not a gap to
    paper over here. Model downloads (the wake-word front end, the
    wake phrase, SFace) happen here, synchronously, the first time a
    fresh install ever reaches a paired state.
    """
    hub_credentials = _hub_credentials_reader(link, base_url)
    wakeword_paths = ensure_wakeword_models(cache_dir)
    wake_engine = OpenWakeWordEngine(
        wake_phrase_model=wakeword_paths[WAKE_PHRASE.file],
        melspec_model=wakeword_paths[MELSPECTROGRAM.file],
        embedding_model=wakeword_paths[EMBEDDING.file],
    )
    audio_playback = AudioPlayback(client)
    return ConversationLoop(
        client=client,
        expression_engine=ExpressionEngine(client, REACHY_MINI_PROFILE),
        audio_capture=AudioCapture(client),
        audio_playback=audio_playback,
        wake_scorer=WakeScorer(wake_engine, client),
        stt_client=SttStreamClient(base_url, session_cookie),
        turn_client=TurnClient(base_url, session_cookie),
        tts_client=TtsPlaybackClient(base_url, session_cookie, audio_playback),
        hub_credentials=hub_credentials,
        face_detector=FiveLandmarkDetector(),
        face_embedder=ensure_embedder(cache_dir),
        face_gallery=FaceGallery(model_id=_FACE_MODEL_ID, model_sha256=SFACE.sha256),
    )


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
        return link.hub_client.session_cookie or "", last_known_good_url[0]

    return read


def run_paired_body(
    client: ReachyMiniClient,
    link: LinkLifecycle,
    stop_event: threading.Event,
    *,
    cache_dir: Path,
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
        paired = False
        while not stop_event.is_set():
            if link.state.paired:
                paired = True
                break
            stop_event.wait(_STOP_POLL_INTERVAL_S)
        if not paired:
            return

        pairing = link.pairing_store.load()
        if pairing is None:
            # Paired per LinkLifecycle's in-memory state but the file
            # it just wrote is unreadable - report as body_lost's own
            # sibling rather than crash the process on a torn write.
            logger.error("link reports paired but the pairing record could not be read")
            return
        session_cookie = link.hub_client.session_cookie
        if not session_cookie:
            # Same shape as the unreadable-pairing-record case above: a
            # code review (2026-09-28) caught this silently falling
            # back to "" and building every hub client anyway, which
            # would only surface as an opaque 401 deep inside the first
            # real turn instead of a clear error right here.
            logger.error("link reports paired but has no session cookie")
            return

        build_result: list[ConversationLoop | Exception] = []

        def build_loop() -> None:
            try:
                build_result.append(
                    _build_conversation_loop(
                        client, session_cookie, pairing.base_url, cache_dir, link
                    )
                )
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
        self.link = LinkLifecycle(
            store,
            HubLinkClient(store),
            discover=discover_hub,
        )
        # The base class only wires static files + index.html; the
        # settings page's own JS polls this for live pairing state.
        if self.settings_app is not None:

            @self.settings_app.get("/api/state")
            async def link_state() -> dict:
                state = self.link.state
                return {
                    "paired": state.paired,
                    "code": state.code,
                    "hub_instance_id": state.hub_instance_id,
                }

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        """Run the body: install the SIGINT handler, start the hub link
        on its own thread, then hold neutral until paired and run the
        real conversation loop for the rest of the process's life."""
        previous_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _sigint_handler(stop_event))
        link_thread = threading.Thread(
            target=self.link.run, args=(stop_event,), name="hub-link", daemon=True
        )
        link_thread.start()
        try:
            client = ReachyMiniClient(REACHY_MINI_PROFILE, reachy=reachy_mini)
            run_paired_body(client, self.link, stop_event, cache_dir=_default_models_cache_dir())
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
