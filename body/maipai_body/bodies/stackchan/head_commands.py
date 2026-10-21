"""Spoken head movement, answered on the robot without asking the hub.

"Look left", "look down a little", "nod", "shake your head", "look around" and "look straight"
move the head through the same Robot seam as every other head move (safe angle limits, the lease,
the emergency-stop latch), say one short line, and return to centre after ``RETURN_AFTER_S``
unless the person says "stay". Left and right are the robot's own left and right.

A request that clearly asks for movement but is not one of these ("turn around", "spin",
"look over there") gets one fixed reply instead of reaching the hub, whose model answers "I can't".
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
MAX_COMMANDS_PER_MIN = 30
SPEED = 120  # moderate: the profile range is 100 to 150
SLOW = 100

CAN_DO = "I can look left, right, up or down."
CANT_NOW = "I can't move right now."

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
_CENTRE = re.compile(
    r"\b(look straight|straight ahead|look forward|look ahead|face forward|face me|look at me|"
    r"look back at me|center|centre|look front|face front|look level)\b"
)
_AROUND = re.compile(r"\b(look around|look all around|scan the room|look about)\b")
_NOD = re.compile(r"\b(nod|say yes|nod yes)\b")
_SHAKE = re.compile(r"\b(shake|say no|shake no)\b")
_STAY = re.compile(r"\b(stay|hold still|stay there|stay like that|freeze|keep looking)\b")
_ASKS_TO_SEE = re.compile(r"\b(tell|describe|what|read|see|show|who)\b")
_UNSUPPORTED = re.compile(
    r"\b(turn around|spin|rotate|twirl|look over there|look over here|look behind|"
    r"walk|come here|go there|follow me|jump|wave|dance|move forward|move back|move closer)\b"
)


@dataclass(frozen=True)
class HeadCommand:
    kind: str  # "look", "centre", "around", "nod", "shake", "stay" or "cannot"
    direction: str | None = None  # left, right, up or down (for "look")
    amount: str = "normal"  # little, normal or far


def _normalise(text: str) -> str:
    spoken = re.sub(r"[^\w' ]+", " ", text.lower())
    spoken = _FILLERS.sub(" ", spoken)
    return re.sub(r"\s+", " ", spoken).strip()


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
        return HeadCommand("look", direction, amount)
    return None


def target_for(command: HeadCommand) -> tuple[int, int]:
    """Yaw and pitch in degrees for a "look" command (the robot's own left is negative yaw)."""
    scale = _AMOUNT[command.amount]
    yaw, pitch = CENTRE_YAW, CENTRE_PITCH
    if command.direction == "left":
        yaw = -round(_BASE_YAW * scale)
    elif command.direction == "right":
        yaw = round(_BASE_YAW * scale)
    elif command.direction == "up":
        pitch = CENTRE_PITCH + round(_BASE_PITCH * scale)
    # "down" is level: the head cannot tilt below it, so it comes back from any raised pose.
    return yaw, pitch


def spoken_line(command: HeadCommand) -> str:
    if command.kind == "look":
        return f"Looking {command.direction}."
    if command.kind == "around":
        return "Looking around."
    if command.kind == "cannot":
        return CAN_DO
    return ""  # centre, nod, shake and stay need no words


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
    ) -> None:
        self._move = move
        self._blocked = blocked
        self._hold_pose = hold_pose
        self._clock = clock
        self._sleep = sleep
        self._return_after_s = return_after_s
        self._start_timer = start_timer or self._thread_timer
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
            self._perform(command)
        except Exception as exc:
            logger.warning("StackChan head command %s failed: %s", command.kind, exc)
            return CANT_NOW
        if command.kind != "centre":
            self._hold_pose(self._return_after_s + 1.0)
            self._schedule_return()
        return spoken_line(command)

    def _perform(self, command: HeadCommand) -> None:
        if command.kind == "look":
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

    def _schedule_return(self) -> None:
        with self._lock:
            self._timer = self._start_timer(self._return_after_s, self._return_to_centre)

    def _cancel_return(self) -> None:
        with self._lock:
            timer, self._timer = self._timer, None
        cancel = getattr(timer, "cancel", None)
        if callable(cancel):
            cancel()

    def _return_to_centre(self) -> None:
        with self._lock:
            self._timer = None
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
