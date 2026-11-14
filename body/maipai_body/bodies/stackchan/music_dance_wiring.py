"""Wire the music dance (music_dance.py) to a running StackChan service.

One function, ``wire_music_dance``: builds the controller from the little dance's runner (its gates,
its ring and its stop handling), hooks the unit's ``music_feat`` events (``behavior.music_feat``,
called from ``wake_on_touch``), the touch and shake events (chained after the dance's own
``behavior.dance_events``) and the hub's ``music_test`` device command (``behavior.music_command``),
and starts the half-second ticker that lets a session end when the music stops.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from maipai_body.bodies.stackchan.dance import DanceRunner
from maipai_body.bodies.stackchan.music_dance import (
    AUTO_PLAN,
    CALM_PLAN,
    DANCE_PLAN,
    MusicDance,
    MusicDanceHooks,
    nod_steps,
    parse_music_feat,
)
from maipai_body.bodies.stackchan.music_identify import MusicIdentify, MusicIdentifyHooks

logger = logging.getLogger("maipai_body.bodies.stackchan.music_dance_wiring")

TICK_S = 0.5
SWITCH_RETRY_S = 15.0
SWITCH_TOOL = "self.music.set"
NOTES_TOOL = "self.face.music_notes"  # firmware patch 123: notes on the face while it dances
TITLE_TOOL = "self.face.song_title"


class MusicFeatureSwitch:
    """Tells the unit whether to analyse the room's sound (firmware patch 100's ``self.music.set``).

    The features run only while the setting ``robot.dance.auto`` is on and the robot is neither
    muted nor in full quiet; otherwise the unit does no analysis and sends no ``music_feat``
    events. The unit keeps its last state in RAM and flash, but the host states it again on every
    connect and retries a failed call every ``SWITCH_RETRY_S`` seconds, so the two cannot stay
    apart."""

    def __init__(
        self,
        call: Callable[[str, dict], object],
        *,
        auto: Callable[[], bool],
        silenced: Callable[[], bool],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._call = call
        self._auto = auto
        self._silenced = silenced
        self._clock = clock
        self._sent: bool | None = None
        self._failed_at = float("-inf")
        self._lock = threading.Lock()

    @property
    def wanted(self) -> bool:
        return bool(self._auto()) and not bool(self._silenced())

    @property
    def sent(self) -> bool | None:
        return self._sent

    def sync(self, *, force: bool = False) -> None:
        with self._lock:
            want = self.wanted
            now = self._clock()
            if not force and self._sent is want:
                return
            if self._sent is None and now - self._failed_at < SWITCH_RETRY_S and not force:
                return
            try:
                self._call(SWITCH_TOOL, {"enabled": want})
            except Exception:
                self._failed_at = now
                self._sent = None
                logger.warning("StackChan music features switch failed; will retry", exc_info=True)
                return
            self._sent = want
            logger.info("StackChan music features %s", "on" if want else "off")

    def call(self, tool: str, arguments: dict) -> object:
        """A unit tool through the same channel (the music notes and the song title)."""
        return self._call(tool, arguments)

    def apply_settings(self, _values: dict) -> None:
        self.sync()

    def on_session(self, _device_id: object = None) -> None:
        """A (re)connect: state it again, whatever was sent before."""
        self.sync(force=True)


def wire_music_dance(
    *,
    behavior: Any,
    runner: DanceRunner,
    move_head: Callable[[int, int, int], object],
    centre_pitch: int,
    speed: int,
    clock: Callable[[], float] = time.monotonic,
    start_ticker: bool = True,
    switch: MusicFeatureSwitch | None = None,
    identify_post: Callable[[bytes], dict | None] | None = None,
    identify_setting: Callable[[], str] | None = None,
    identify_call_tool: Callable[[str, dict], object] | None = None,
    identify_spawn: Callable[[Callable[[], None]], object] | None = None,
) -> MusicDance:
    def stop_bob() -> None:
        if switch is not None:
            switch.call("self.robot.stop_dance", {})

    def nod(face: str, cancelled: Callable[[], bool]) -> None:
        behavior.show_face(face)
        if switch is not None:
            # The head nods up and down on the beat on the unit until the dance starts.
            try:
                switch.call("self.robot.dance", {"name": "bob"})
                return
            except Exception:
                logger.debug(
                    "StackChan music bob could not start; using the one nod", exc_info=True
                )
        try:
            for yaw, pitch, move_speed, pause in nod_steps(centre_pitch, speed):
                if cancelled():
                    break
                move_head(yaw, pitch, move_speed)
                time.sleep(pause)
        finally:
            try:
                move_head(0, centre_pitch, speed)  # one move back to level, always
            except Exception:
                logger.debug("StackChan music nod could not level the head", exc_info=True)

    def wonder() -> None:
        # No music any more: the thinking look (eyes up and to the side), then the usual face,
        # unless the music came back or something else took the face in the meantime.
        if runner.situation().in_turn:
            return
        behavior.show_face("thinking")

        def back() -> None:
            if controller.state in ("break", "spent", "idle") and not runner.situation().in_turn:
                behavior.show_face("neutral")

        timer = threading.Timer(3.0, back)
        timer.daemon = True
        timer.start()

    def restore_face() -> None:
        if not runner.situation().in_turn:
            behavior.show_face("neutral")

    def request_dance() -> tuple[bool, str]:
        plan = {"full": AUTO_PLAN, "dance": DANCE_PLAN, "calm": CALM_PLAN}[controller.plan]
        reply = runner.request("auto", plan)
        return reply.started, reply.why

    identify = None
    if identify_post is not None and identify_setting is not None:
        identify = MusicIdentify(
            MusicIdentifyHooks(
                call_tool=identify_call_tool
                or (switch.call if switch else (lambda _name, _args: None)),
                post_clip=identify_post,
                situation=runner.situation,
                setting=identify_setting,
                clock=clock,
                spawn=identify_spawn,
            )
        )

    controller = MusicDance(
        MusicDanceHooks(
            request_dance=request_dance,
            stop_dance=runner.stop,
            dance_running=lambda: runner.running,
            nod=nod,
            restore_face=restore_face,
            situation=runner.situation,
            notes=(lambda count: switch.call(NOTES_TOOL, {"count": count})) if switch else None,
            on_session_start=(lambda: identify.on_session_start(clock())) if identify else None,
            on_session_end=identify.on_session_end if identify else None,
            stop_bob=stop_bob if switch else None,
            wonder=wonder,
        ),
        behavior.dance_settings,
    )

    def on_music_feat(extra: dict, now: float) -> None:
        feat = parse_music_feat(extra)
        if feat is None:
            logger.debug("StackChan music_feat event ignored: missing or odd fields %r", extra)
            return
        controller.feed(feat, clock())

    previous_events = behavior.dance_events

    def on_events(events: list, now: float) -> None:
        if previous_events is not None:
            previous_events(events, now)
        controller.on_events(events, clock())

    def command(payload: dict) -> dict:
        ok, why = controller.start_test(clock(), fast=bool(payload.get("fast")))
        return {"music_test": "started" if ok else "refused", "why": why}

    def listen_song_command(payload: dict) -> dict:
        request_id = payload.get("request_id") if isinstance(payload, dict) else None
        seconds = payload.get("seconds", 10) if isinstance(payload, dict) else None
        if (
            not isinstance(request_id, str)
            or not 1 <= len(request_id) <= 64
            or any(not (char.isascii() and (char.isalnum())) for char in request_id)
        ):
            return {"listen_song": "refused", "why": "request_id must be 1 to 64 letters or digits"}
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not 5 <= seconds <= 15:
            return {"listen_song": "refused", "why": "seconds must be an integer from 5 to 15"}
        if identify is None:
            return {"listen_song": "refused", "why": "song naming is not ready"}
        return identify.listen_now(request_id, seconds, clock())

    behavior.music_feat = on_music_feat
    if identify is not None:
        behavior.music_clip = identify.on_clip_event
    behavior.dance_events = on_events
    behavior.music_command = command
    behavior.listen_song_command = listen_song_command

    if start_ticker:

        def run() -> None:
            warned = float("-inf")
            while True:
                time.sleep(TICK_S)
                try:
                    if switch is not None:
                        switch.sync()  # a no-op unless the last call failed (then rate limited)
                    controller.tick(clock())
                except Exception:
                    now = time.monotonic()
                    if now - warned >= 60.0:
                        warned = now
                        logger.warning("StackChan music dance tick failed", exc_info=True)

        threading.Thread(target=run, name="stackchan-music-tick", daemon=True).start()
    return controller
