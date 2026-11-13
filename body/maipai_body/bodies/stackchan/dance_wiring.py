"""Wire the little dance (dance.py) to a running StackChan service.

One function, ``wire_dance``, so the service's own wiring in app.py stays a few lines: it builds the
runner from the live robot, light service, night rule and behaviour, then hooks the three triggers
(the spoken ask through ``HeadCommander``, the hub's "dance" device command through
``behavior.dance_command`` and the three taps through ``behavior.dance_events``) and tells the
behaviour when a dance is running so the ambient head moves, the face watchdog and the look-around
stay out of its way.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from maipai_body.bodies.stackchan.dance import (
    LED_COUNT,
    DanceHooks,
    DanceRunner,
    DanceSituation,
    TapCounter,
)

logger = logging.getLogger("maipai_body.bodies.stackchan.dance_wiring")

BATTERY_TTL_S = 5.0  # the battery is read over the link; a dance checks it every quarter second


def wire_dance(
    *,
    voice: Any,
    behavior: Any,
    light: Any,
    night: Any,
    head_commander: Any,
    level_head: Callable[[], object],
    device_connected: Callable[[], bool],
    # HOOK: no muted or full-quiet flag exists in the settings registry yet (the modes are being
    # designed). Return a plain reason ("muted", "full quiet") while one is on, else None.
    full_quiet_reason: Callable[[], str | None] = lambda: None,
) -> DanceRunner:
    battery: dict[str, Any] = {"at": float("-inf"), "percent": None, "charging": None}

    def read_battery() -> None:
        now = time.monotonic()
        if now - battery["at"] < BATTERY_TTL_S:
            return
        battery["at"] = now
        try:
            status = voice.robot.client.get_battery_status()
            percent, charging = status.get("percent"), status.get("charging")
            battery["percent"] = (
                percent if isinstance(percent, int) and not isinstance(percent, bool) else None
            )
            battery["charging"] = charging if isinstance(charging, bool) else None
        except Exception:
            battery["percent"] = None  # unknown: a dance on battery is refused
            battery["charging"] = None

    def situation() -> DanceSituation:
        read_battery()
        facts = light.facts
        return DanceSituation(
            awake=behavior._rest.stage == "awake",
            night=bool(night.night),
            in_turn=behavior._active.is_set(),
            estop=bool(voice.robot.robot.estop_engaged),
            upright=not behavior.pose_held(),
            connected=bool(device_connected()),
            offline=facts.offline,
            camera_cue=facts.camera,
            live_cue=facts.live,
            battery_percent=battery["percent"],
            charging=battery["charging"],
            battery_low=facts.battery_low,
            full_quiet=full_quiet_reason(),
        )

    def write_ring(pixels: list[tuple[int, int, int]]) -> None:
        # Through the adapter, so the camera cue's pink still wins if a picture is being taken.
        voice.robot.robot.leds.many(
            [{"index": i, "rgb": list(pixels[i])} for i in range(LED_COUNT)]
        )

    def wake() -> None:
        now = time.monotonic()
        behavior._last_person_seen = now  # the rest policy treats the request as a person
        behavior.rest_step(now)

    def hold(held: bool) -> None:
        behavior._note_own_move()  # the head's own motion is not the picture changing

    companion = voice.robot.client.companion
    hooks = DanceHooks(
        start_dance=lambda name: companion().dance(name),
        stop_dance=lambda: companion().stop_dance(),
        show_face=lambda expression: behavior.show_face(expression),
        write_ring=write_ring,
        take_ring=light.take_ring,
        give_ring_back=light.give_ring_back,
        level_head=level_head,
        situation=situation,
        wake=wake,
        hold=hold,
    )
    runner = DanceRunner(hooks, behavior.dance_settings)
    taps = TapCounter()

    def on_events(events: list, now: float) -> None:
        runner.on_events(events, now)
        if runner.running:
            taps.reset()
        elif taps.feed(events, now, upright=not behavior.pose_held()):
            runner.request("taps")

    def command(_payload: dict) -> dict:
        reply = runner.request("hub")
        return {"dance": "started" if reply.started else "refused", "why": reply.why}

    behavior.dance_active = lambda: runner.running
    behavior.dance_events = on_events
    behavior.dance_command = command
    head_commander.dance = lambda: runner.request("voice").line
    return runner
