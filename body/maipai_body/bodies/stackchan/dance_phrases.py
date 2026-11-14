"""Dance rounds that alternate head nods and side-to-side sways in time with the beat (host side).

Owner 2026-11-14: "you need to alternate through side to side and head nods". The unit already
moves the head on the beat of the song (firmware patches 128 and 131, ``BeatSwayModifier``): the
``bob`` dance is the head nodding up and down on the beat, the ``happy`` dance is the head swaying
side to side on the beat, ``robot`` is the stiff turns and ``look_around`` looks about. This module
only decides the ORDER and LENGTH of those moves: phrases of eight beats at the song's tempo,
cycling nod, side, nod, turns, so the dance is never one move for the whole round.

Nothing here listens to sound, and a round has the same length as before (``DANCE_S``), so the
dance controller's round boundaries, its still listening gap and its stop rules are unchanged.
A phrase boundary is only a new ``self.robot.dance`` name; it adds no head moves from the host
(the unit runs every move, patch 038's 40 moves a minute limit is not touched).
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from dataclasses import dataclass

from maipai_body.bodies.stackchan.dance import Plan

BEATS_PER_PHRASE = 8
MIN_PHRASE_S = 3.0  # a very fast song: not shorter than this (the unit needs a moment to settle)
MAX_PHRASE_S = 6.0  # a very slow song: not longer than this
DEFAULT_BPM = 110  # no tempo known: a middle one
MIN_BPM = 60
MAX_BPM = 187

# One cycle: nod, side to side, nod, stiff turns (then the same again). (move name, face).
CYCLE: tuple[tuple[str, str], ...] = (
    ("bob", "happy"),
    ("happy", "happy"),
    ("bob", "excited"),
    ("robot", "happy"),
    ("happy", "happy"),
    ("look_around", "happy"),
)


def fold_bpm(bpm: float) -> float:
    """A tempo folded into the range the beat finder reports (halves and doubles are the same
    song)."""
    if bpm <= 0:
        return 0.0
    while bpm > MAX_BPM:
        bpm /= 2
    while bpm < MIN_BPM:
        bpm *= 2
    return bpm


def steady_bpm(readings: Iterable[float]) -> float:
    """The median of the recent folded tempo readings; 0 when there are none."""
    folded = [fold_bpm(value) for value in readings if value and value > 0]
    if not folded:
        return 0.0
    return float(statistics.median(folded))


def phrase_seconds(bpm: float) -> float:
    """Eight beats at the tempo, held between MIN_PHRASE_S and MAX_PHRASE_S."""
    tempo = bpm if MIN_BPM <= bpm <= MAX_BPM else DEFAULT_BPM
    return min(MAX_PHRASE_S, max(MIN_PHRASE_S, BEATS_PER_PHRASE * 60.0 / tempo))


@dataclass(frozen=True)
class Phrase:
    start_s: float
    move: str
    face: str


def phrases(total_s: float, bpm: float, *, offset: int = 0) -> list[Phrase]:
    """The phrases that fill ``total_s`` seconds at the tempo, starting ``offset`` steps into the
    cycle (so the second round of a block does not begin with the same move as the first)."""
    length = phrase_seconds(bpm)
    out: list[Phrase] = []
    at = 0.0
    index = offset
    while at < total_s - 0.5:  # a last phrase under half a second is not worth a move
        move, face = CYCLE[index % len(CYCLE)]
        out.append(Phrase(round(at, 3), move, face))
        at += length
        index += 1
    return out


def dance_script(
    total_s: float, bpm: float, *, offset: int = 0, start_s: float = 0.0
) -> tuple[tuple[float, str, str], ...]:
    """Plan steps ((seconds, "face" or "dance", name)) for the dance part of a round. A face is
    set only when it changes, a move at every phrase start."""
    steps: list[tuple[float, str, str]] = []
    last_face = ""
    for phrase in phrases(total_s, bpm, offset=offset):
        at = start_s + phrase.start_s
        if phrase.face != last_face:
            steps.append((at, "face", phrase.face))
            last_face = phrase.face
        steps.append((at, "dance", phrase.move))
    return tuple(steps)


def phrase_plan(
    base: Plan,
    *,
    bpm: float,
    dance_from_s: float,
    offset: int = 0,
) -> Plan:
    """``base`` with its dance part (from ``dance_from_s`` to its end) replaced by the beat
    phrases. The build-up before ``dance_from_s``, the ring and the total length stay as they
    were, so the round boundary is exactly where it was."""
    head = tuple(step for step in base.script if step[0] < dance_from_s)
    tail = dance_script(base.total_s - dance_from_s, bpm, offset=offset, start_s=dance_from_s)
    return Plan(head + tail, base.total_s, base.ring)


class PhraseOffset:
    """Counts rounds so each round begins one step further along the cycle."""

    def __init__(self) -> None:
        self._rounds = 0

    def next(self) -> int:
        value = self._rounds
        self._rounds += 1
        return value

    def reset(self) -> None:
        self._rounds = 0


__all__ = [
    "CYCLE",
    "PhraseOffset",
    "dance_script",
    "fold_bpm",
    "phrase_plan",
    "phrase_seconds",
    "phrases",
    "steady_bpm",
]
