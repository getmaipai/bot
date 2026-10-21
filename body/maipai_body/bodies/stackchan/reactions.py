"""How the robot reacts to being touched, shaken and praised (owner requests 2026-10-21).

Touch, swipe and shake events come from the unit (patch 021's event queue). The unit already shows
its own dizzy and heart faces for a shake and a stroke; this adds what only the host can do: a short
spoken line after a shake, and a loving heart only when it is earned. The heart is rare on purpose:
a pet, or kind words such as "you're so helpful", or a very cute picture, and never twice within
a minute.
"""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable

logger = logging.getLogger("maipai_body.bodies.stackchan.reactions")

SHAKE_LINES = ("Whoa!", "Hey! Easy!", "Eep! Where are we going?")
SHAKE_COOLDOWN_S = 20.0
# How long a reaction face (heart, surprise) stays before the neutral face is put back. The unit's
# own happy face after a stroke is open-mouthed and was left on far too long. It is also the only
# gap between two pet reactions: while one plays no new one starts, and the next real pet reacts at
# once when it ends (owner ruling 2026-10-21: no cooldown after the petted animation).
FACE_HOLD_S = 3.0
SYMBOL_RETRY_S = 600.0

# What it would love to hear. A short, closed list: a heart must be earned, not guessed.
_LOVE_CUES = re.compile(
    r"\b(you'?re so helpful|you are so helpful|thank you so much|thanks so much|i love you|"
    r"love you|you'?re the best|you are the best|good robot|you'?re adorable|you are adorable|"
    r"you'?re so cute|you are so cute|you'?re cute|so adorable)\b"
)
# Reply moods from the hub's cue that mean a very cute picture or real affection.
LOVE_MOODS = frozenset({"love", "affection", "adoration"})

_PET_EVENTS = {"head_touch"}
_SWIPE_EVENTS = {"head_swipe_forward", "head_swipe_back"}


def has_love_cue(text: str | None) -> bool:
    spoken = re.sub(r"[^\w' ]+", " ", (text or "").lower())
    return bool(_LOVE_CUES.search(re.sub(r"\s+", " ", spoken)))


class Reactions:
    """Decides what the robot shows and says; the callables do it."""

    def __init__(
        self,
        *,
        face: Callable[[str], object],
        say: Callable[[str], bool],
        quiet: Callable[[], bool] = lambda: False,
        busy: Callable[[], bool] = lambda: False,
        symbol: Callable[[str], object] | None = None,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self._face = face
        self._say = say
        self._quiet = quiet
        self._busy = busy
        self._symbol = symbol
        self._clock = clock
        self._rng = rng or random.Random()
        self._last_shake = float("-inf")
        self._playing_until = float("-inf")
        self._symbol_retry_at = float("-inf")
        self._last_line: str | None = None
        self._neutral_at: float | None = None

    # -- the unit's events ----------------------------------------------------

    def on_events(self, kinds: list[str]) -> None:
        """Touch, swipe and shake events read from the unit since the last look."""
        if self._busy():
            return  # in a conversation: the reply owns the face and the voice
        if "shake" in kinds:
            self._shaken()
        if any(kind in _PET_EVENTS for kind in kinds) or any(k in _SWIPE_EVENTS for k in kinds):
            # The unit shows its own open-mouthed happy face for a stroke; take it back soon.
            self._hold_face()
        if any(kind in _PET_EVENTS or kind in _SWIPE_EVENTS for kind in kinds):
            self._petted()
        # A stroke across the head already makes the unit show its own happy face and heart.

    def _shaken(self) -> None:
        now = self._clock()
        if now - self._last_shake < SHAKE_COOLDOWN_S:
            return
        self._last_shake = now
        self._face("surprised")
        self._hold_face()
        if self._quiet():
            logger.info("StackChan was shaken (quiet hours: face only)")
            return
        line = self._pick_line()
        logger.info("StackChan was shaken; says %r", line)
        self._say(line)

    def _pick_line(self) -> str:
        choices = [line for line in SHAKE_LINES if line != self._last_line] or list(SHAKE_LINES)
        self._last_line = self._rng.choice(choices)
        return self._last_line

    def _petted(self) -> None:
        if self.heart("petted"):
            logger.info("StackChan was petted")

    def _hold_face(self) -> None:
        self._neutral_at = self._clock() + FACE_HOLD_S

    def tick(self) -> None:
        """Put the neutral face back once a reaction face has been held long enough."""
        if self._neutral_at is None or self._clock() < self._neutral_at:
            return
        self._neutral_at = None
        if not self._busy():
            self._face("neutral")

    # -- the heart, rare on purpose ----------------------------------------------

    def on_user_words(self, text: str | None) -> None:
        if has_love_cue(text):
            self.heart("kind words")

    def on_reply_mood(self, mood: str | None) -> None:
        if mood in LOVE_MOODS:
            self.heart("a loving reply")

    def heart(self, reason: str) -> bool:
        """Show the heart (or, until the unit can, a smile), unless one is still playing."""
        now = self._clock()
        if now < self._playing_until:
            return False
        self._playing_until = now + FACE_HOLD_S
        shown = False
        if self._symbol is not None and now >= self._symbol_retry_at:
            try:
                self._symbol("heart")
                shown = True
            except Exception:
                # This firmware has no symbol tool yet: smile instead, and do not ask for a while.
                self._symbol_retry_at = now + SYMBOL_RETRY_S
        if not shown:
            self._face("happy")
        self._hold_face()
        logger.info("StackChan heart (%s): %s", reason, "heart" if shown else "smile")
        return True
