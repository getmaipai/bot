"""Spoken head movement, answered on the robot without asking the hub.

"Look left", "look down a little", "nod", "shake your head", "look around" and "look straight"
move the head through the same Robot seam as every other head move (safe angle limits, the lease,
the emergency-stop latch), say one short line, and return to centre after ``RETURN_AFTER_S``
unless the person says "stay". Left and right are the robot's own left and right.

Owner request 2026-11-12 ("when I tell stackchan to turn, it needs to move according to what I
said"):
- "turn to me", "look at me", "face me", "over here", "I'm here", "up here", "I'm down here",
  "find me": look for the person's face now (head_search.py, "ask": a slow eased look up and to
  each side; "I'm down here" looks level and to the sides, the head cannot tilt below level). The
  back-off after earlier misses is ignored, because the person asked. A face ends the look and the
  face following keeps the head on it; if none is found the robot says so (app.py).
- "turn away", "look away", "look the other way": about 45 degrees away from the face being
  followed (to the left when none is), held for the normal return time. "Turn around" turns the
  head as far to the side as it goes and says honestly that it cannot go all the way around.
- "turn left" / "turn right" (also "turn left 30 degrees", "turn right ninety degrees", "a little",
  "all the way") HOLD the new heading for ``HOLD_TURN_S``; it ends on "look straight", "centre",
  "face forward", on a new command, or when a face is found. "Look left/right/up/down" still
  return after ``RETURN_AFTER_S``. The head only tilts up from level, so "look down" is level.

A request that clearly asks for movement but is not one of these ("spin", "walk", "dance") gets
one fixed reply instead of reaching the hub, whose model answers "I can't".
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from maipai_body.bodies.stackchan.profile import CENTRE_PITCH_DEG

logger = logging.getLogger("maipai_body.bodies.stackchan.head_commands")

CENTRE_YAW = 0
CENTRE_PITCH = CENTRE_PITCH_DEG  # level; the head only travels up from here
RETURN_AFTER_S = 5.0
HOLD_TURN_S = 300.0  # a "turn left" keeps its heading this long
MAX_COMMANDS_PER_MIN = 30
SPEED = 120  # moderate: the profile range is 100 to 150
SLOW = 100
MAX_TURN_DEG = 90  # the most any spoken turn asks for (the Robot clamps to the profile again)
AWAY_DEG = 45

CAN_DO = "I can look left, right, up or down."
CANT_NOW = "I can't move right now."
LOOKING_FOR_YOU = "Looking for you."
LOOKING_AT_YOU = "Here you are."
NOT_FOUND = "I can't see you yet, say something or move closer."
NOT_FOUND_LEVEL = "I can't see you yet. I can only look level, so come up a little or move closer."
LOOK_AWAY = "Looking away."
TURN_AROUND = "I can turn my head about 90 degrees, not all the way around."
LEVEL_ONLY = "I can only look level."

# Yaw and pitch targets in degrees from the centre pose (yaw 0, pitch 45). The Robot clamps all of
# them to the profile again, so these only choose the size of the move.
_AMOUNT = {"little": 0.45, "normal": 1.0, "far": 2.0}
_BASE_YAW = 45
_BASE_PITCH = 25

_FILLERS = re.compile(
    r"\b(please|ok|okay|hey|hi|um|uh|now|thanks|thank you|stack ?chan|can you|could you|"
    r"would you|will you|go ahead and|just|your head|the head|to your|to the|to)\b"
)
_QUESTION = re.compile(r"^(how|what|why|when|where|which|who|is|are|do|does|did)\b")
_LITTLE = re.compile(r"\b(a little|a bit|slightly|little|bit)\b")
_FAR = re.compile(r"\b(all the way|as far as you can|as far|fully|far)\b")
_VERB = r"(?:look|turn|face|tilt|move|point|glance|go)"
_DIRECTION = re.compile(
    rf"\b{_VERB}\b(?:\s+\w+){{0,3}}?\s+\b(left|right|up|down|upward|downward)\b"
)
_HOLDING_VERB = re.compile(r"\b(turn|face)\b")
_NUMBER_WORDS = {
    "ten": 10,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty five": 45,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_DEGREES = re.compile(r"\b(\d{1,3}|" + "|".join(_NUMBER_WORDS) + r")\s*(?:degrees?|deg)\b")
# The head is pointed at the person (the "turn to me" family). "to" is a filler, so "turn to me"
# arrives here as "turn me".
_FACE = re.compile(
    r"\b(turn me|turn toward me|turn towards me|turn this way|look at me|look back at me|"
    r"face me|look this way|find me|look for me|here i am)\b"
    r"|^(?:(?:i'?m|i am|im|look|turn) )?(?:over|up|down) here$"
    r"|^(?:i'?m|i am|im) here$"
)
_FACE_LEVEL = re.compile(r"\bdown here$")
_AWAY = re.compile(
    r"\b(turn away|look away|face away|look the other way|turn the other way|"
    r"look somewhere else)\b"
)
_TURN_AROUND = re.compile(r"\b(turn around|turn round|turn all the way around|look behind)\b")
_CENTRE = re.compile(
    r"\b(look straight|straight ahead|look forward|look ahead|face forward|"
    r"center|centre|look front|face front|look level)\b"
)
_AROUND = re.compile(r"\b(look around|look all around|scan the room|look about)\b")
_NOD = re.compile(r"\b(nod|say yes|nod yes)\b")
_SHAKE = re.compile(r"\b(shake|say no|shake no)\b")
_STAY = re.compile(r"\b(stay|hold still|stay there|stay like that|freeze|keep looking)\b")
_ASKS_TO_SEE = re.compile(r"\b(tell|describe|what|read|see|show|who)\b")
_UNSUPPORTED = re.compile(
    r"\b(spin|rotate|twirl|look over there|"
    r"walk|come here|go there|follow me|jump|wave|dance|move forward|move back|move closer)\b"
)


@dataclass(frozen=True)
class HeadCommand:
    # "look", "centre", "around", "nod", "shake", "stay", "cannot", "face" (point at the person),
    # "away" (look away from the person) or "turnaround" (as far to the side as it goes)
    kind: str
    direction: str | None = None  # left, right, up or down (for "look")
    amount: str = "normal"  # little, normal or far
    degrees: int | None = None  # a spoken size ("turn left 30 degrees"), overrides amount
    hold: bool = False  # keep the heading (a "turn"), do not return after RETURN_AFTER_S
    level_only: bool = False  # "I'm down here": look level and to the sides only


def _normalise(text: str) -> str:
    spoken = re.sub(r"[^\w' ]+", " ", text.lower())
    spoken = _FILLERS.sub(" ", spoken)
    return re.sub(r"\s+", " ", spoken).strip()


def _spoken_degrees(spoken: str) -> int | None:
    match = _DEGREES.search(spoken)
    if match is None:
        return None
    raw = match.group(1)
    value = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
    return max(1, min(value, MAX_TURN_DEG))


def parse_head_command(text: str) -> HeadCommand | None:
    """The head command in what the person said, or None (then it goes on to the hub).

    A garbled opening word is harmless (the match searches the sentence). A question, or a long
    sentence, is not a command: "how do I turn right on red" belongs to the hub."""
    spoken = _normalise(text)
    words = spoken.split()
    if not words or len(words) > 8 or _QUESTION.match(spoken):
        return None
    # "look down and tell me what you see" asks about the picture, not for a move.
    if _ASKS_TO_SEE.search(spoken):
        return None
    short = len(words) <= 4
    if _FACE.search(spoken) and len(words) <= 6:
        return HeadCommand("face", level_only=bool(_FACE_LEVEL.search(spoken)))
    if _AWAY.search(spoken) and len(words) <= 5:
        return HeadCommand("away")
    if _TURN_AROUND.search(spoken) and len(words) <= 6:
        return HeadCommand("turnaround")
    if _STAY.search(spoken) and short:
        return HeadCommand("stay")
    if _AROUND.search(spoken) and short:
        return HeadCommand("around")
    if _NOD.search(spoken) and short:
        return HeadCommand("nod")
    if _SHAKE.search(spoken) and short and re.search(r"\b(head|no)\b|^shake$", spoken):
        return HeadCommand("shake")
    if _CENTRE.search(spoken) and len(words) <= 5:
        return HeadCommand("centre")
    if _UNSUPPORTED.search(spoken) and short:
        return HeadCommand("cannot")
    match = _DIRECTION.search(spoken)
    if match:
        direction = {"upward": "up", "downward": "down"}.get(match.group(1), match.group(1))
        amount = "little" if _LITTLE.search(spoken) else "far" if _FAR.search(spoken) else "normal"
        hold = bool(_HOLDING_VERB.search(spoken)) and direction in ("left", "right")
        return HeadCommand("look", direction, amount, _spoken_degrees(spoken), hold)
    return None


def target_for(command: HeadCommand) -> tuple[int, int]:
    """Yaw and pitch in degrees for a "look" command (the robot's own left is negative yaw)."""
    scale = _AMOUNT[command.amount]
    yaw, pitch = CENTRE_YAW, CENTRE_PITCH
    if command.direction in ("left", "right"):
        size = command.degrees if command.degrees is not None else round(_BASE_YAW * scale)
        size = min(size, MAX_TURN_DEG)
        yaw = -size if command.direction == "left" else size
    elif command.direction == "up":
        size = command.degrees if command.degrees is not None else round(_BASE_PITCH * scale)
        pitch = CENTRE_PITCH + size
    # "down" is level: the head cannot tilt below it, so it comes back from any raised pose.
    return yaw, pitch


def away_yaw(face_yaw: float | None, delta: int = AWAY_DEG) -> int:
    """The yaw about ``delta`` degrees away from the face being followed (left when none is)."""
    if face_yaw is None:
        return -delta
    if face_yaw >= 0:
        return round(face_yaw - delta)
    return round(face_yaw + delta)


def spoken_line(command: HeadCommand) -> str:
    if command.kind == "look":
        if command.direction == "down":
            return LEVEL_ONLY
        return f"{'Turning' if command.hold else 'Looking'} {command.direction}."
    if command.kind == "around":
        return "Looking around."
    if command.kind == "away":
        return LOOK_AWAY
    if command.kind == "turnaround":
        return TURN_AROUND
    if command.kind == "cannot":
        return CAN_DO
    return ""  # centre, nod, shake and stay need no words


def gaze_detail(command: HeadCommand) -> str:
    """The reason noted for the gaze ("why are you looking there"), named in gaze.py."""
    if command.kind == "look" and command.hold:
        return f"turn_{command.direction}"
    return command.direction or command.kind


MoveFn = Callable[[int, int, int], object]


class HeadCommander:
    """Runs a spoken head command through ``move(yaw_deg, pitch_deg, speed)``.

    ``blocked()`` names why the head must not move now (the unit is charging, the stop is
    latched) or returns None. Commands are explicit requests, so the ambient head gate does not
    apply, but they have their own limit of ``MAX_COMMANDS_PER_MIN``."""

    def __init__(
        self,
        move: MoveFn,
        *,
        blocked: Callable[[], str | None] = lambda: None,
        hold_pose: Callable[[float], None] = lambda seconds: None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        return_after_s: float = RETURN_AFTER_S,
        start_timer: Callable[[float, Callable[[], None]], object] | None = None,
        on_done: Callable[[HeadCommand], object] | None = None,
        find_face: Callable[[bool], str] | None = None,
        face_yaw: Callable[[], float | None] = lambda: None,
    ) -> None:
        self._move = move
        self._blocked = blocked
        self._hold_pose = hold_pose
        self._clock = clock
        self._sleep = sleep
        self._return_after_s = return_after_s
        self._start_timer = start_timer or self._thread_timer
        self._on_done = on_done
        # find_face(level_only) starts a look for the person's face now and answers "turned" (a
        # fresh face was in view, the head is on it) or "searching" (the look runs after this reply
        # and the robot says so itself if it finds nobody). face_yaw() is the yaw of the face being
        # followed in degrees (left negative), or None.
        self._find_face = find_face
        self._face_yaw = face_yaw
        self._holding = False
        self._recent: deque[float] = deque()
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def run(self, command: HeadCommand) -> str:
        """Do the command; returns the line to say ("" for nothing)."""
        if command.kind == "cannot":
            return CAN_DO
        if command.kind == "stay":
            self._cancel_return()
            return ""
        reason = self._blocked()
        if reason is not None:
            logger.info("StackChan head command %s refused: %s", command.kind, reason)
            return CANT_NOW
        now = self._clock()
        while self._recent and now - self._recent[0] >= 60.0:
            self._recent.popleft()
        if len(self._recent) >= MAX_COMMANDS_PER_MIN:
            logger.warning(
                "StackChan head commands refused: more than %d a minute", len(self._recent)
            )
            return CANT_NOW
        self._recent.append(now)
        self._cancel_return()
        try:
            line = self._perform(command)
        except Exception as exc:
            logger.warning("StackChan head command %s failed: %s", command.kind, exc)
            return CANT_NOW
        if self._on_done is not None:
            self._on_done(command)  # the gaze reason: "you asked me to look left"
        if command.kind == "face":
            return line  # the face look moves the head itself and keeps it on the face
        if command.kind != "centre":
            seconds = HOLD_TURN_S if self._holds(command) else self._return_after_s
            self._holding = self._holds(command)
            self._hold_pose(seconds + 1.0)
            self._schedule_return(seconds)
        return line or spoken_line(command)

    @staticmethod
    def _holds(command: HeadCommand) -> bool:
        return command.kind == "look" and command.hold

    def face_found(self) -> None:
        """A face was found: a held turn ends (the head follows the face instead)."""
        if self._holding:
            self._cancel_return()

    def _find(self, command: HeadCommand) -> str:
        if self._find_face is None:
            raise RuntimeError("no way to look for a face")
        found = self._find_face(command.level_only)
        return LOOKING_AT_YOU if found == "turned" else LOOKING_FOR_YOU

    def _perform(self, command: HeadCommand) -> str:
        """Move for the command; returns the line to say, or "" to use ``spoken_line``."""
        if command.kind == "face":
            return self._find(command)
        if command.kind in ("away", "turnaround"):
            delta = AWAY_DEG if command.kind == "away" else MAX_TURN_DEG
            self._move(away_yaw(self._face_yaw(), delta), CENTRE_PITCH, SPEED)
        elif command.kind == "look":
            yaw, pitch = target_for(command)
            self._move(yaw, pitch, SPEED)
        elif command.kind == "centre":
            self._move(CENTRE_YAW, CENTRE_PITCH, SPEED)
        elif command.kind == "around":
            for yaw in (-60, 60, 0):
                self._move(yaw, CENTRE_PITCH, SLOW)
                self._sleep(1.4)
        elif command.kind == "nod":
            for _ in range(2):
                self._move(CENTRE_YAW, CENTRE_PITCH + 12, SPEED)
                self._sleep(0.35)
                self._move(CENTRE_YAW, CENTRE_PITCH, SPEED)
                self._sleep(0.35)
            self._move(CENTRE_YAW, CENTRE_PITCH, SPEED)
        elif command.kind == "shake":
            for _ in range(2):
                self._move(-25, CENTRE_PITCH, SPEED)
                self._sleep(0.35)
                self._move(25, CENTRE_PITCH, SPEED)
                self._sleep(0.35)
            self._move(CENTRE_YAW, CENTRE_PITCH, SPEED)
        return ""

    def _schedule_return(self, seconds: float | None = None) -> None:
        with self._lock:
            self._timer = self._start_timer(
                self._return_after_s if seconds is None else seconds, self._return_to_centre
            )

    def _cancel_return(self) -> None:
        self._holding = False
        with self._lock:
            timer, self._timer = self._timer, None
        cancel = getattr(timer, "cancel", None)
        if callable(cancel):
            cancel()

    def _return_to_centre(self) -> None:
        with self._lock:
            self._timer = None
        self._holding = False
        try:
            if self._blocked() is None:
                self._move(CENTRE_YAW, CENTRE_PITCH, SPEED)
        except Exception as exc:
            logger.warning("StackChan head could not return to centre: %s", exc)

    @staticmethod
    def _thread_timer(seconds: float, callback: Callable[[], None]) -> threading.Timer:
        timer = threading.Timer(seconds, callback)
        timer.daemon = True
        timer.start()
        return timer
