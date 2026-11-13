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
    DANCE_PLAN,
    MusicDance,
    MusicDanceHooks,
    nod_steps,
    parse_music_feat,
)

logger = logging.getLogger("maipai_body.bodies.stackchan.music_dance_wiring")

TICK_S = 0.5
SWITCH_RETRY_S = 15.0
SWITCH_TOOL = "self.music.set"


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
) -> MusicDance:
    def nod(face: str, cancelled: Callable[[], bool]) -> None:
        behavior.show_face(face)
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

    def restore_face() -> None:
        if not runner.situation().in_turn:
            behavior.show_face("neutral")

    def request_dance() -> tuple[bool, str]:
        reply = runner.request("auto", AUTO_PLAN if controller.full_plan else DANCE_PLAN)
        return reply.started, reply.why

    controller = MusicDance(
        MusicDanceHooks(
            request_dance=request_dance,
            stop_dance=runner.stop,
            dance_running=lambda: runner.running,
            nod=nod,
            restore_face=restore_face,
            situation=runner.situation,
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

    behavior.music_feat = on_music_feat
    behavior.dance_events = on_events
    behavior.music_command = command

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
