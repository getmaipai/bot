"""The StackChan little dance: an on-request routine of about 11 seconds (host side only).

Design: the StackChan dance note of 2026-11-13, stage "the little dance". Nothing here listens to
music; the music-aware dance comes later, after measurements.

What it is: the firmware's own keyframe dances (patch 020) played back to back, happy (4.2 s),
robot (2.7 s), happy (4.2 s), with a host face between the moves (wink, surprised) and a light show
on the ring. The head never moves from a host loop: the firmware refuses more than 40 head moves a
minute (patch 038), so every head move of the dance runs inside the unit, started by one tool call.
The host makes one call per dance, one face frame per gap and about four ring frames a second
(those are not head moves). A dance ends with one move back to level.

Who may start it, and when:
- Triggers: the spoken ask ("dance", "do a dance", "can you dance", "dance for me", "show me a
  dance"), and the hub's "dance" device command (the Settings button);
  music comes later. Taps on the head do not start a dance.
- Refused: not awake (a spoken ask means awake; the hub command wakes the unit first),
  during a turn (a spoken ask starts it once its own turn ends), while the emergency stop is
  latched, when the unit is tipped or carried, offline or unpaired, in full quiet or muted
  (``full_quiet_reason``, a hook until the settings registry has such a flag), with the battery at
  20 percent or less while not charging (or unknown) and within ``MIN_GAP_S`` of the last dance.
- At night an asked dance (voice or hub) is head and face only: no ring, no spoken line.
- The ring show is the one decorative use of the ring (lights standard): colours outside the status
  meanings (gold, lime, mint, a warm sparkle), always two or more at once, always moving, half
  brightness. A privacy cue (the live green, the camera pink) or any status cue ends the dance and
  so the show; the show never draws over one.
- Ends at once on a touch, the wake word or any turn, a shake or tilt, a camera cue, a low battery,
  going offline, the emergency stop, or the settings turning it off. Then the ring goes dark (the
  normal rules repaint it) and the head goes back to level.

Settings (registry keys, device scope, honoured by the bot): ``robot.dance.enabled`` (default true)
and ``robot.dance.show_ring`` (default true). All timings here are design defaults, unmeasured on a
unit.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from maipai_body.bodies.stackchan.profile import LED_CHANNEL_MAX

logger = logging.getLogger("maipai_body.bodies.stackchan.dance")

ENABLED_KEY = "robot.dance.enabled"
SHOW_RING_KEY = "robot.dance.show_ring"

LED_COUNT = 12
RING_BRIGHTNESS = 0.5  # by day; the show never runs at night
TICK_S = 0.25  # one ring frame and one interrupt check every tick
START_GRACE_S = 1.0  # a touch or shake this soon after the start is the dance's own motion
START_WAIT_S = 10.0  # a spoken ask starts once its own turn is over, but waits no longer than this

MIN_GAP_S = 60.0  # between the end of one dance and the start of the next
MIN_BATTERY_PERCENT = 20  # a dance on battery needs more than this

LINE_START = "Let's dance."
LINE_NOT_NOW = "Not right now."
LINE_OFF = "Dancing is turned off."

# (name, seconds): the firmware's keyframe dances, durations added up from dance.h (patch 020).
HAPPY_S = 4.2
ROBOT_S = 2.7
GAP_S = 0.3  # between two dances: the host face change; the firmware dance replaces a running one
# (time from the start, action, argument)
SCRIPT: tuple[tuple[float, str, str], ...] = (
    (0.0, "face", "happy"),
    (0.0, "dance", "happy"),
    (HAPPY_S, "face", "wink"),
    (HAPPY_S + GAP_S, "dance", "robot"),
    (HAPPY_S + GAP_S + ROBOT_S, "face", "surprised"),
    (HAPPY_S + 2 * GAP_S + ROBOT_S, "face", "happy"),
    (HAPPY_S + 2 * GAP_S + ROBOT_S, "dance", "happy"),
)
TOTAL_S = HAPPY_S + 2 * GAP_S + ROBOT_S + HAPPY_S  # 11.7 s

# The one place the show names colours: fractions of full scale. None may be a status colour
# (ring.py RING_RGB: white, green, blue, amber, cyan, violet, pink) and none is red.
GOLD = (1.0, 0.8, 0.0)
LIME = (0.6, 1.0, 0.0)
MINT = (0.3, 1.0, 0.6)
SPARKLE = (1.0, 0.95, 0.75)
SHOW_COLOURS = (GOLD, LIME, MINT, SPARKLE)

Rgb = tuple[int, int, int]


def _scaled(colour: tuple[float, float, float], level: float = 1.0) -> Rgb:
    r, g, b = (
        max(0, min(LED_CHANNEL_MAX, round(LED_CHANNEL_MAX * c * level * RING_BRIGHTNESS)))
        for c in colour
    )
    return (r, g, b)


DARK: Rgb = (0, 0, 0)


def ring_frame(tick: int, phase: int) -> list[Rgb]:
    """The 12 pixels at ring tick ``tick`` (every ``TICK_S``) in show phase ``phase`` (0 to 2).

    Every frame has at least two different colours lit and every frame differs from the one before
    (the show is always moving). Pure, so a test can walk the whole show."""
    pixels = [DARK] * LED_COUNT
    if phase == 0:  # chase: gold and lime walk round, mint trails each
        head = tick % LED_COUNT
        other = (head + LED_COUNT // 2) % LED_COUNT
        pixels[(head - 1) % LED_COUNT] = _scaled(MINT, 0.5)
        pixels[(other - 1) % LED_COUNT] = _scaled(MINT, 0.5)
        pixels[head] = _scaled(GOLD)
        pixels[other] = _scaled(LIME)
    elif phase == 1:  # beat pulse: the whole ring steps between gold/mint and lime/gold
        bright = 1.0 if tick % 2 == 0 else 0.55
        first, second = (GOLD, MINT) if (tick // 2) % 2 == 0 else (LIME, GOLD)
        pixels = [_scaled(first if i % 2 == 0 else second, bright) for i in range(LED_COUNT)]
    else:  # sparkle: a few warm pixels over a slow gold and lime wash that moves round
        for i in range(LED_COUNT):
            pixels[i] = _scaled(GOLD if (i + tick) % 3 else LIME, 0.35)
        for k in range(3):
            pixels[(tick * 5 + k * 4) % LED_COUNT] = _scaled(SPARKLE)
    return pixels


def phase_at(t_s: float) -> int:
    """Which ring pattern runs at ``t_s`` seconds into the dance."""
    if t_s < HAPPY_S:
        return 0
    if t_s < HAPPY_S + 2 * GAP_S + ROBOT_S:
        return 1
    return 2


# ---------------------------------------------------------------- the ask, in words

_DANCE = re.compile(
    r"^(?:(?:let's|lets|do|show me|start|give me|put on|have)\s+)?"
    r"(?:an?\s+|another\s+|one\s+)?"
    r"(?:(?:little|quick|small|short|happy)\s+)?dance"
    r"(?:\s+(?:for me|a little|a bit|again|for us))?$"
)


def is_dance_request(spoken: str) -> bool:
    """True for "dance", "do a dance", "dance for me", "show me a dance" and the like.

    ``spoken`` is already lowercased with its fillers ("can you", "please") removed by
    head_commands. A question about dancing ("what is a dance") or a sentence that merely
    mentions it does not match."""
    return bool(_DANCE.match(spoken.strip()))


# ---------------------------------------------------------------- settings


class DanceSettings:
    """``robot.dance.enabled`` and ``robot.dance.show_ring`` (both default true)."""

    def __init__(self) -> None:
        self.enabled = True
        self.show_ring = True

    def apply(self, values: Mapping[str, object]) -> None:
        enabled = values.get(ENABLED_KEY)
        if isinstance(enabled, bool):
            self.enabled = enabled
        show_ring = values.get(SHOW_RING_KEY)
        if isinstance(show_ring, bool):
            self.show_ring = show_ring


# ---------------------------------------------------------------- the routine


@dataclass(frozen=True)
class DanceSituation:
    """What the gates and the interrupts look at; read fresh each time."""

    awake: bool = True
    night: bool = False
    in_turn: bool = False
    estop: bool = False
    upright: bool = True
    connected: bool = True
    offline: bool = False
    camera_cue: bool = False  # the camera pink: a picture is being taken
    live_cue: bool = False  # the live green: audio is streaming to the hub
    battery_percent: int | None = None
    charging: bool | None = None
    battery_low: bool = False  # the light service's low-battery flag
    full_quiet: str | None = None  # why the unit is muted or in full quiet, else None


@dataclass(frozen=True)
class DanceReply:
    started: bool
    line: str = ""  # what to say ("" for nothing)
    why: str = ""  # the refusal's reason, for logs and the hub's answer


@dataclass
class DanceHooks:
    """The robot side of the dance, all injected (a test passes recorders)."""

    start_dance: Callable[[str], object]  # the firmware keyframe dance by name
    stop_dance: Callable[[], object]
    show_face: Callable[[str], object]
    write_ring: Callable[[list[Rgb]], object]  # all 12 pixels
    take_ring: Callable[[], object]  # the light service stops painting
    give_ring_back: Callable[[], object]  # dark, and the normal rules repaint
    level_head: Callable[[], object]  # one move back to level
    situation: Callable[[], DanceSituation]
    wake: Callable[[], object] | None = None  # wake a sleeping unit (the hub's command)
    hold: Callable[[bool], object] = lambda held: None  # keep the ambient moves and watchdog off


# Reasons after which the head is not moved and the face is not repainted: someone else is
# drawing (a turn, a reaction to the touch) or the unit is not ours to move.
_LEAVE_HEAD = frozenset({"estop", "turn", "tilt", "shake", "offline"})
_LEAVE_FACE = frozenset({"turn", "touch", "shake", "tilt"})


class DanceRunner:
    """Gates, runs and ends the little dance; one dance at a time."""

    def __init__(
        self,
        hooks: DanceHooks,
        settings: DanceSettings | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[float], bool] | None = None,
        spawn: Callable[[Callable[[], None]], object] | None = None,
    ) -> None:
        self._hooks = hooks
        self.settings = settings or DanceSettings()
        self._clock = clock
        self._stop = threading.Event()
        self._wait = wait or self._real_wait
        self._spawn = spawn or self._thread
        self._lock = threading.Lock()
        self._running = False
        self._last_end = float("-inf")
        self._started_at = float("-inf")
        self.last_end_reason = ""

    # -- state

    @property
    def running(self) -> bool:
        return self._running

    # -- triggers

    def request(self, trigger: str) -> DanceReply:
        """Ask for a dance. ``trigger`` is "voice" or "hub".

        The gates run now. A started dance runs on its own thread (a spoken ask first waits for its
        own turn to end); the reply's line is what the caller says."""
        if trigger not in ("voice", "hub"):
            raise ValueError(f"unknown dance trigger {trigger!r}")
        now = self._clock()
        with self._lock:
            refusal = self._refusal(trigger, now)
            if refusal is not None:
                why, line = refusal
                logger.info("StackChan dance (%s) refused: %s", trigger, why)
                return DanceReply(False, line, why)
            self._running = True
            self._started_at = now
            self._stop.clear()
            self._last_end = float("inf")  # no second dance can slip in before this one ends
        situation = self._hooks.situation()
        quiet_start = situation.night
        self._spawn(lambda: self._run(trigger))
        return DanceReply(True, "" if quiet_start else LINE_START)

    def stop(self, reason: str) -> None:
        """End a running dance at once (a touch, a shake, a settings change ...)."""
        if not self._running:
            return
        self.last_end_reason = reason
        self._stop.set()

    def on_events(self, events: Iterable, now: float | None = None) -> None:
        """The unit's head and shake events: they end a running dance (after the start grace)."""
        if not self._running:
            return
        now = self._clock() if now is None else now
        if now - self._started_at < START_GRACE_S:
            return
        for event in events:
            kind = getattr(event, "kind", None)
            if kind == "shake":
                self.stop("shake")
                return
            if kind in ("head_touch", "head_swipe_forward", "head_swipe_back"):
                self.stop("touch")
                return

    # -- gates

    def _refusal(self, trigger: str, now: float) -> tuple[str, str] | None:
        if self._running:
            return ("a dance is already running", "")
        if not self.settings.enabled:
            return ("robot.dance.enabled is off", LINE_OFF if trigger == "voice" else "")
        situation = self._hooks.situation()
        if situation.full_quiet:
            return (f"full quiet or muted ({situation.full_quiet})", "")
        if situation.estop:
            return ("the emergency stop is latched", LINE_NOT_NOW)
        if not situation.connected or situation.offline:
            return ("the unit is offline", "")
        if not situation.upright:
            return ("the unit is not upright", LINE_NOT_NOW)
        if situation.camera_cue or situation.live_cue:
            return ("a camera or live cue is showing", LINE_NOT_NOW)
        if situation.in_turn and trigger != "voice":
            return ("a turn is on", LINE_NOT_NOW)
        if not situation.awake and not (trigger == "hub" and self._hooks.wake is not None):
            return ("the unit is asleep", "")
        if situation.charging is not True:
            if situation.battery_percent is None:
                return ("the battery level is unknown", LINE_NOT_NOW)
            if situation.battery_percent <= MIN_BATTERY_PERCENT:
                return (f"battery {situation.battery_percent}% and not charging", LINE_NOT_NOW)
        if now - self._last_end < MIN_GAP_S:
            return ("the last dance was under a minute ago", LINE_NOT_NOW)
        return None

    def _interrupt(self, situation: DanceSituation) -> str | None:
        """Why a running dance must end now, or None."""
        if situation.estop:
            return "estop"
        if situation.in_turn:
            return "turn"
        if not situation.upright:
            return "tilt"
        if situation.camera_cue:
            return "picture"
        if situation.live_cue:
            return "turn"
        if not situation.connected or situation.offline:
            return "offline"
        if situation.battery_low or (
            situation.charging is False
            and situation.battery_percent is not None
            and situation.battery_percent <= MIN_BATTERY_PERCENT
        ):
            return "battery"
        if situation.full_quiet:
            return "quiet"
        if not self.settings.enabled:
            return "settings"
        if not situation.awake:
            return "asleep"
        return None

    # -- the dance

    def _run(self, trigger: str) -> None:
        reason = "done"
        started = False
        try:
            reason = self._prepare(trigger)
            if reason == "":
                started = True
                reason = self._play()
        except Exception:
            logger.warning("StackChan dance failed", exc_info=True)
            reason = "error"
        finally:
            self._end(reason, played=started)

    def _prepare(self, trigger: str) -> str:
        """Wake the unit (the hub's command) and wait for the spoken ask's own turn to end."""
        waited = 0.0
        woke = False
        while True:
            if self._stop.is_set():
                return self.last_end_reason or "stopped"
            situation = self._hooks.situation()
            if situation.estop:
                return "estop"
            if situation.awake and not situation.in_turn:
                return ""
            if not situation.awake and trigger == "hub" and not woke and self._hooks.wake:
                woke = True
                self._hooks.wake()
            if waited >= START_WAIT_S:
                return "turn" if situation.in_turn else "asleep"
            if self._wait(TICK_S):
                return self.last_end_reason or "stopped"
            waited += TICK_S

    def _play(self) -> str:
        hooks = self._hooks
        situation = hooks.situation()
        quiet = situation.night
        ring_on = self.settings.show_ring and not quiet
        hooks.hold(True)
        if ring_on:
            hooks.take_ring()
        begin = self._clock()
        script = list(SCRIPT)
        tick = 0
        while True:
            elapsed = self._clock() - begin
            while script and script[0][0] <= elapsed + 1e-9:
                _, action, arg = script.pop(0)
                if action == "dance":
                    hooks.start_dance(arg)
                else:
                    hooks.show_face(arg)
            situation = hooks.situation()
            why = self._interrupt(situation)
            if why is not None:
                self.last_end_reason = why
                return why
            if self._stop.is_set():
                return self.last_end_reason or "stopped"
            if elapsed >= TOTAL_S:
                return "done"
            if ring_on and not (situation.camera_cue or situation.live_cue):
                hooks.write_ring(ring_frame(tick, phase_at(elapsed)))
            tick += 1
            if self._wait(TICK_S):
                return self.last_end_reason or "stopped"

    def _end(self, reason: str, *, played: bool) -> None:
        """Stop the unit's dance, darken the ring, level the head, release the holds."""
        hooks = self._hooks
        if played:
            for step in (
                hooks.stop_dance,
                hooks.give_ring_back,
            ):
                try:
                    step()
                except Exception:
                    logger.warning("StackChan dance end step failed", exc_info=True)
            if reason not in _LEAVE_HEAD:
                try:
                    hooks.level_head()
                except Exception:
                    logger.warning("StackChan dance could not level the head", exc_info=True)
            if reason not in _LEAVE_FACE:
                try:
                    hooks.show_face("neutral")
                except Exception:
                    logger.warning("StackChan dance could not restore the face", exc_info=True)
        try:
            hooks.hold(False)
        except Exception:
            logger.warning("StackChan dance could not release its hold", exc_info=True)
        self.last_end_reason = reason
        self._last_end = self._clock() if played else float("-inf")
        self._running = False
        logger.info("StackChan dance ended (%s)", reason)

    # -- plumbing

    def _real_wait(self, seconds: float) -> bool:
        return self._stop.wait(seconds)

    @staticmethod
    def _thread(target: Callable[[], None]) -> threading.Thread:
        thread = threading.Thread(target=target, name="stackchan-dance", daemon=True)
        thread.start()
        return thread


__all__ = [
    "DanceHooks",
    "DanceReply",
    "DanceRunner",
    "DanceSettings",
    "DanceSituation",
    "is_dance_request",
    "ring_frame",
]
