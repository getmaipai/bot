"""G6 (receive side): the turn round trip's reply, read as it streams.

`POST /api/turn/stream` (newline-delimited JSON, not SSE - `home`'s
own `routes/turn.ts` comment: "one real HTTP response body, no
text/event-stream framing to parse for a wire shape this simple").
Every event this module reads is real, verified in `home`'s own
`wire.ts` `TurnStreamEvent` union, not assumed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import requests

from maipai_body.expression.cue import Cue, Phase


class TurnLinkLost(RuntimeError):
    """The HTTP connection itself failed mid-stream (section 7's own
    `link_lost` case) - distinct from a `{type:"error"}` event, which
    is a normal terminal result on a connection that's still open."""


class TurnAuthFailed(RuntimeError):
    """The session cookie was rejected (401) or a robot credential is
    unrotated (403 - ROBOT-DEVICE-01's own gate) - distinct from
    :class:`TurnLinkLost`, since the fix is re-redeeming through
    `HubLinkClient`, not reconnecting the same stale credential."""


@dataclass
class TurnEvent:
    """One thing worth acting on from the stream: a cue to render, or
    the reply text once it's known. Not every wire event produces one
    (`status`, `reasoning`, `spoken_cue` have no cue mapping at the
    floor - EXPR-03's own future job, not this module's)."""

    cue: Cue | None = None
    reply_text: str | None = None  # set only on the DONE event
    conversation_id: str | None = None
    turn_id: str | None = None


@dataclass
class _TurnStreamState:
    cue_seq: int = 0
    conversation_id: str | None = None
    turn_id: str | None = None
    reply_parts: list[str] = field(default_factory=list)

    def next_cue_seq(self) -> int:
        self.cue_seq += 1
        return self.cue_seq


class TurnClient:
    """Calls the hub's own streaming turn route and yields
    :class:`TurnEvent` as the response arrives - a generator, so a
    caller (G9's future run loop) can render each cue the instant it's
    known rather than waiting for the whole turn to finish."""

    def __init__(
        self, base_url: str, session_cookie: str, *, session: requests.Session | None = None
    ) -> None:
        if not session_cookie:
            # HubLinkClient.session_cookie is str | None (None before any
            # successful pair()/refresh()) - a caller passing that straight
            # through without checking would otherwise silently send the
            # literal header value "Cookie: session=None", which fails
            # auth in a way indistinguishable from a real bad cookie
            # instead of surfacing the caller's own bug clearly.
            raise ValueError("session_cookie is empty - the hub link isn't paired yet")
        self._base_url = base_url
        self._cookie = session_cookie
        self._session = session or requests.Session()

    def stream(
        self,
        text: str,
        *,
        speaker_evidence: dict[str, Any] | None = None,
        present: list[dict[str, Any]] | None = None,
        conversation_id: str | None = None,
    ) -> Iterator[TurnEvent]:
        """POSTs the turn and yields one :class:`TurnEvent` per cue-
        worthy wire event, in order: SIGNAL (if any), then DONE (with
        the full reply text) or CANCEL. Raises :class:`TurnAuthFailed`
        on 401/403 (the cookie needs re-redeeming, not a reconnect) or
        :class:`TurnLinkLost` on any other connection failure - never
        for a normal `{type:"error"}` event, which is still a CANCEL
        event, not an exception, since it's the hub's own considered
        answer, not a transport problem."""
        body = {
            "surface": "robot",
            "text": text,
            "spoken": True,
            "speaker_evidence": speaker_evidence,
            "present": present,
        }
        if conversation_id:
            body["conversation_id"] = conversation_id
        state = _TurnStreamState()
        try:
            response = self._session.post(
                f"{self._base_url}/api/turn/stream",
                json=body,
                headers={"Cookie": f"session={self._cookie}"},
                stream=True,
                timeout=(10, 120),
            )
            if response.status_code in (401, 403):
                raise TurnAuthFailed(
                    f"hub rejected the turn request: {response.status_code} {response.text[:200]}"
                )
            response.raise_for_status()
            yield from self._read_lines(response, state)
        except (TurnLinkLost, TurnAuthFailed):
            raise
        except requests.RequestException as exc:
            raise TurnLinkLost(f"turn stream connection failed: {exc}") from exc

    def _read_lines(
        self, response: requests.Response, state: _TurnStreamState
    ) -> Iterator[TurnEvent]:
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            try:
                message = json.loads(raw_line)
            except (TypeError, ValueError):
                continue  # a malformed line is skipped, never fatal to the turn
            event = self._handle_line(message, state)
            if event is not None:
                yield event

    def _handle_line(self, message: dict, state: _TurnStreamState) -> TurnEvent | None:
        kind = message.get("type")
        if kind == "turn_meta":
            state.conversation_id = message.get("conversation_id")
            state.turn_id = message.get("turn_id")
            return None
        if kind == "delta":
            text = message.get("text")
            if text:
                state.reply_parts.append(text)
            return None
        if kind == "signal":
            signal = message.get("signal") or {}
            cue = Cue(
                phase=Phase.SIGNAL,
                cue_seq=state.next_cue_seq(),
                primary_act=signal.get("primary_act"),
                expressed_emotion=signal.get("expressed_emotion"),
                emotion_intensity=signal.get("emotion_intensity"),
            )
            return TurnEvent(cue=cue, conversation_id=state.conversation_id, turn_id=state.turn_id)
        if kind == "done":
            cue = Cue(phase=Phase.DONE, cue_seq=state.next_cue_seq())
            return TurnEvent(
                cue=cue,
                reply_text="".join(state.reply_parts),
                conversation_id=state.conversation_id,
                turn_id=state.turn_id,
            )
        if kind == "error":
            # Every error kind maps to CANCEL at the floor (a cancelled
            # turn, a safety refusal, a generic engine failure): the
            # audit names turn_cancelled specifically, but nothing calls
            # for a different stop-the-presentation cue per error code,
            # and CANCEL's own primitive (stop) is the safe response to
            # any of them.
            cue = Cue(phase=Phase.CANCEL, cue_seq=state.next_cue_seq())
            return TurnEvent(cue=cue, conversation_id=state.conversation_id, turn_id=state.turn_id)
        return None  # status/reasoning/spoken_cue: no cue mapping at the floor
