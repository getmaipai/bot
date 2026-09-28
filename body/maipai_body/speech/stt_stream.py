"""G3+G6 (send side): stream captured audio to the hub's own STT
session and know when to give up.

The revised design (`docs/dev/robot-streaming-turn-2026-09-28.md`)
folds G3 into this module entirely: there is no local VAD, no
endpointer, no locally-built `Utterance` - the hub's own `SttSession`
(`home/backend/src/lib/sttSession.ts`) already does VAD, pre-roll and
endpointing for any client that streams raw PCM to it. The one piece
of local logic the hub's session genuinely cannot provide is deciding
when to give up on a wake that nobody followed with speech - the
wake-patience timer, `WAKE_PATIENCE_S` (the legacy value, 6.0s).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Literal

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

from maipai_body.speech.capture import AudioCapture

logger = logging.getLogger("maipai_body.speech.stt_stream")

WAKE_PATIENCE_S = 6.0
# How long a single recv() waits for a server message before looping
# back to poll capture again - short enough that audio keeps flowing
# in near real time, long enough not to busy-loop.
_RECV_POLL_S = 0.05


class SttStreamError(RuntimeError):
    """The WS connection itself failed (link lost mid-stream, section 7's
    own `link_lost` case) - distinct from a `{t:"error"}` the session
    sends over a connection that's still open."""


@dataclass
class SttStreamResult:
    kind: Literal["final", "no_speech", "timeout", "error"]
    text: str | None = None
    error: str | None = None


def _ws_url(base_url: str) -> str:
    """`http(s)://host:port` -> `ws(s)://host:port/api/stt/stream` -
    the same origin the redeemed session cookie is scoped to."""
    scheme = "wss" if base_url.startswith("https://") else "ws"
    rest = base_url.split("://", 1)[1]
    return f"{scheme}://{rest}/api/stt/stream"


class SttStreamClient:
    """One call to :meth:`run` is one wake's worth of listening: open
    the stream, forward audio from the moment it's called, and return
    the instant the hub's own session reaches a terminal state or the
    wake-patience timer expires with nobody having spoken."""

    def __init__(
        self,
        base_url: str,
        session_cookie: str,
        *,
        wake_patience_s: float = WAKE_PATIENCE_S,
        connect_fn=connect,
    ) -> None:
        if not session_cookie:
            # HubLinkClient.session_cookie is str | None (None before any
            # successful pair()/refresh()) - a caller passing that straight
            # through without checking would otherwise silently send the
            # literal header value "Cookie: session=None" on the WS
            # handshake instead of surfacing the caller's own bug clearly.
            raise ValueError("session_cookie is empty - the hub link isn't paired yet")
        self._url = _ws_url(base_url)
        self._cookie = session_cookie
        self._wake_patience_s = wake_patience_s
        self._connect = connect_fn

    def run(self, capture: AudioCapture) -> SttStreamResult:
        """Blocks until a terminal event, or the wake-patience timeout.
        Raises :class:`SttStreamError` if the connection itself drops
        mid-stream (never for a session-level `{t:"error"}`, which is a
        normal terminal result, not a transport failure)."""
        try:
            with self._connect(
                self._url, additional_headers={"Cookie": f"session={self._cookie}"}
            ) as ws:
                return self._run_over(ws, capture)
        except SttStreamError:
            raise
        except Exception as exc:  # noqa: BLE001 - any transport failure is link_lost
            raise SttStreamError(f"hub stt connection failed: {exc}") from exc

    def _run_over(self, ws: ClientConnection, capture: AudioCapture) -> SttStreamResult:
        self._await_ready(ws)
        deadline = time.monotonic() + self._wake_patience_s
        speaking_seen = False
        while True:
            for block in capture.poll_blocks():
                ws.send(block.tobytes())

            message = self._recv_nonblocking(ws)
            if message is not None:
                result = self._handle_message(message)
                if result is not None:
                    return result
                if message.get("t") == "vad" and message.get("speaking"):
                    speaking_seen = True

            if not speaking_seen and time.monotonic() >= deadline:
                return self._give_up(ws)

    def _await_ready(self, ws: ClientConnection) -> None:
        raw = ws.recv(timeout=10)
        message = json.loads(raw)
        if message.get("t") != "ready":
            raise SttStreamError(f"expected {{t: 'ready'}}, got {message!r}")

    def _recv_nonblocking(self, ws: ClientConnection) -> dict | None:
        try:
            raw = ws.recv(timeout=_RECV_POLL_S)
        except TimeoutError:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("malformed message from hub stt session: %r", raw)
            return None

    def _handle_message(self, message: dict) -> SttStreamResult | None:
        t = message.get("t")
        if t == "final":
            return SttStreamResult(kind="final", text=message.get("v"))
        if t == "no_speech":
            return SttStreamResult(kind="no_speech")
        if t == "error":
            return SttStreamResult(kind="error", error=message.get("v"))
        return None  # vad/partial: handled inline by the caller, or ignored

    def _give_up(self, ws: ClientConnection) -> SttStreamResult:
        """Nobody spoke within the wake-patience window: tell the hub's
        own session to finalize (its own `finalize()` responds
        `no_speech` for an empty buffer, cheap and correct either way),
        then stop - back to sleep, no utterance kept the connection
        open forever. The send and the recv are both guarded: the hub
        can close the connection at either point (a restart, a proxy
        timeout), and either way there is nothing left to wait for -
        still a successful give-up, not a transport error."""
        try:
            ws.send(json.dumps({"t": "end"}))
            raw = ws.recv(timeout=5)
            message = json.loads(raw)
            result = self._handle_message(message)
            if result is not None:
                return result
        except (TimeoutError, ValueError, TypeError, ConnectionClosed):
            pass
        return SttStreamResult(kind="timeout")
