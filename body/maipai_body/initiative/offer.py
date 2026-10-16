"""OFFER-01: the robot's half of a hub initiative offer.

The hub sends an ``offer`` command ``{offer_id, person_id, tier,
non_personal_line}``. The robot shows the antenna offer gesture and listens for
ten seconds, on this robot only, for one of a closed set of phrases (the local
keyword spotter; nothing is sent to the hub while it listens):

* "go ahead", "yes please", "okay go ahead" accept: a normal turn opens with the
  heard phrase as its text and ``ask_answer {offer_id, approved: true}``. The hub
  treats ``approved`` alone as nothing; the phrase and the speaker evidence are
  the consent.
* "not now" sends an ``offer_snooze`` frame (the hub snoozes thirty minutes).
* "no thanks" sends an ``offer_answer`` frame with ``approved: false``.

A wave, a thumbs up, a touch on an antenna and silence never accept. Silence
sends nothing; the hub expires the offer itself.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from maipai_body.speech.kws import (
    ACCEPT_PHRASES,
    DECLINE_PHRASES,
    KeywordEngine,
    offer_tag_to_phrase,
)

logger = logging.getLogger("maipai_body.initiative.offer")

WINDOW_S = 10.0
REOFFER_AT_S = 5.0
DEFER_CAP_S = 120.0
# The spotter state is reset after this many blocks without a hit, so a long
# window never grows one stream without bound.
_RESET_BLOCKS = 200


@dataclass(frozen=True)
class OfferGates:
    """Everything that can stop or delay an offer, injected by the run loop."""

    busy: Callable[[], bool]  # a turn (listening, thinking, speaking) is running
    muted: Callable[[], bool]
    held: Callable[[], bool]
    asleep: Callable[[], bool]
    outage: Callable[[], bool]
    guest_app: Callable[[], bool]  # a guest app owns the body
    attentive: Callable[[str], bool]  # the offer's person is facing the robot
    child_present: Callable[[], bool]


@dataclass
class _Offer:
    offer_id: str
    person_id: str
    tier: str
    line: str | None
    received_at: float


class OfferController:
    def __init__(
        self,
        *,
        engine: KeywordEngine | None,
        poll_blocks: Callable[[], Sequence[Any]],
        render: Callable[[str], bool],
        send_frame: Callable[[dict], bool],
        open_turn: Callable[[str, str, str], None],
        gates: OfferGates,
        speak: Callable[[str], None] | None = None,
        on_window: Callable[[bool], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._engine = engine
        self._poll_blocks = poll_blocks
        self._render = render
        self._send_frame = send_frame
        self._open_turn = open_turn
        self._gates = gates
        self._speak = speak
        self._on_window = on_window
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: _Offer | None = None
        self._active: _Offer | None = None
        self._window_start = 0.0
        self._reoffered = False
        self._fed = 0

    # -- the command handler (channel thread) ---------------------------

    def receive(self, payload: dict) -> dict:
        offer_id = payload.get("offer_id")
        person_id = payload.get("person_id")
        if not isinstance(offer_id, str) or not offer_id:
            raise ValueError("offer command requires an offer_id")
        if not isinstance(person_id, str) or not person_id:
            raise ValueError("offer command requires a person_id")
        tier = payload.get("tier")
        line = payload.get("non_personal_line")
        refusal = self._refusal()
        if refusal is not None:
            return {"offer": "refused", "reason": refusal}
        offer = _Offer(
            offer_id,
            person_id,
            tier if isinstance(tier, str) else "",
            line if isinstance(line, str) and line else None,
            self._clock(),
        )
        with self._lock:
            if self._pending is not None or self._active is not None:
                return {"offer": "refused", "reason": "offer_in_progress"}
            self._pending = offer
        return {"offer": "queued"}

    def _refusal(self) -> str | None:
        """Reasons an offer is dropped on arrival. Busy is not one: it defers."""
        if self._engine is None:
            return "no_spotter"
        g = self._gates
        if g.muted():
            return "muted"
        if g.held():
            return "held"
        if g.asleep():
            return "asleep"
        if g.outage():
            return "outage"
        if g.guest_app():
            return "guest_app"
        if g.child_present():
            return "child_present"
        return None

    # -- the loop thread -------------------------------------------------

    def service(self) -> bool:
        """Advance the offer. True while the robot is in an offer window, so the
        caller leaves the audio to it; False when the caller may score wake."""
        with self._lock:
            active, pending = self._active, self._pending
        if active is not None:
            return self._step_window(active)
        if pending is None:
            return False
        now = self._clock()
        if now - pending.received_at > DEFER_CAP_S or self._refusal() is not None:
            self._drop_pending(pending)
            return False
        if self._gates.busy() or not self._gates.attentive(pending.person_id):
            return False  # deferred: never rendered over a turn or an empty room
        with self._lock:
            self._pending = None
            self._active = pending
        self._window_start = now
        self._reoffered = False
        self._fed = 0
        assert self._engine is not None
        self._engine.begin()
        self._render("offer")
        self._tell_window(True)
        if pending.line and self._speak is not None:
            try:
                self._speak(pending.line)
            except Exception:
                logger.warning("offer line failed", exc_info=True)
        return True

    def _drop_pending(self, offer: _Offer) -> None:
        with self._lock:
            if self._pending is offer:
                self._pending = None

    def _end(self) -> None:
        with self._lock:
            self._active = None
        self._tell_window(False)

    def _tell_window(self, open_: bool) -> None:
        if self._on_window is None:
            return
        try:
            self._on_window(open_)
        except Exception:
            logger.warning("offer window callback failed", exc_info=True)

    def _step_window(self, offer: _Offer) -> bool:
        g = self._gates
        if g.muted() or g.held() or g.asleep() or g.outage() or g.busy():
            self._end()  # the offer ends quietly; the hub expires it
            return False
        elapsed = self._clock() - self._window_start
        assert self._engine is not None
        for block in self._poll_blocks():
            self._fed += 1
            phrase = offer_tag_to_phrase(self._engine.accept(block) or "")
            if self._fed >= _RESET_BLOCKS:
                self._fed = 0
                self._engine.begin()
            if phrase is None:
                continue
            return self._decide(offer, phrase)
        if elapsed >= WINDOW_S:
            self._end()
            self._render("settle")
            return False
        if elapsed >= REOFFER_AT_S and not self._reoffered:
            self._reoffered = True
            self._render("offer")
        return True

    def _decide(self, offer: _Offer, phrase: str) -> bool:
        if phrase in ACCEPT_PHRASES:
            if not self._gates.attentive(offer.person_id):
                return True  # someone else said it; keep listening for the person
            self._end()
            self._open_turn(phrase, offer.offer_id, offer.person_id)
            return False
        if phrase in DECLINE_PHRASES:
            self._end()
            if phrase == "not now":
                frame = {
                    "kind": "offer_snooze",
                    "payload": {"offer_id": offer.offer_id, "source": "voice"},
                }
            else:
                frame = {
                    "kind": "offer_answer",
                    "payload": {
                        "offer_id": offer.offer_id,
                        "approved": False,
                        "source": "voice",
                    },
                }
            if not self._send_frame(frame):
                logger.info("offer reply not sent: the hub channel is down")
            self._render("settle")
            return False
        return True
