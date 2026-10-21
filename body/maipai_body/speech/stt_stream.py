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
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

from maipai_body.speech.capture import AudioCapture

logger = logging.getLogger("maipai_body.speech.stt_stream")

WAKE_PATIENCE_S = 6.0
# How long a single recv() waits for a server message before looping
# back to poll capture again - short enough that audio keeps flowing
# in near real time, long enough not to busy-loop.
_RECV_POLL_S = 0.05
# SPEAK-02: the utterance audio kept locally for the voice embedder. The hub
# never sees a template; this copy never leaves the process. Bounded so a
# long monologue cannot grow it without limit.
_MAX_KEPT_BLOCKS = 1900  # about 60 s of 32 ms blocks
# The hub's vad message trails the audio by its own latency; start the kept
# span this many blocks before it so the first syllable is inside.
_VAD_LEAD_BLOCKS = 10
# Speech that starts just before the patience window ends is still in flight: the hub's vad message
# trails the audio (and the Wi-Fi hop adds to it). Wait this long past the deadline before giving
# up, so a word at the 6 s mark is not cut off by an early end.
_GIVE_UP_GRACE_S = 0.6
# After the end request the hub finalises what it has; transcribing can take seconds when the Mac
# is busy, and a timeout here throws away words the hub would have answered.
_FINAL_WAIT_S = 12.0


class SttStreamError(RuntimeError):
    """The WS connection itself failed (link lost mid-stream, section 7's
    own `link_lost` case) - distinct from a `{t:"error"}` the session
    sends over a connection that's still open."""


@dataclass
class SttStreamResult:
    kind: Literal["final", "no_speech", "timeout", "error"]
    text: str | None = None
    error: str | None = None
    # SPEAK-02: the speech span as 16 kHz mono float32 and how many seconds of
    # it the hub's VAD called speech. Local only: they feed the voice embedder
    # and are never sent anywhere. UNVERIFIED against the real hub's vad
    # cadence (M-07).
    audio: Any = field(default=None, repr=False)
    speech_s: float | None = None


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

    def run(self, capture: AudioCapture, *, patience_s: float | None = None) -> SttStreamResult:
        """Blocks until a terminal event, or the wake-patience timeout.
        Raises :class:`SttStreamError` if the connection itself drops
        mid-stream (never for a session-level `{t:"error"}`, which is a
        normal terminal result, not a transport failure). ``patience_s``
        overrides the wake patience for this call (FOLLOWUP-01's window)."""
        try:
            with self._connect(
                self._url, additional_headers={"Cookie": f"session={self._cookie}"}
            ) as ws:
                return self._run_over(ws, capture, patience_s)
        except SttStreamError:
            raise
        except Exception as exc:  # noqa: BLE001 - any transport failure is link_lost
            raise SttStreamError(f"hub stt connection failed: {exc}") from exc

    def _run_over(
        self, ws: ClientConnection, capture: AudioCapture, patience_s: float | None = None
    ) -> SttStreamResult:
        self._await_ready(ws)
        deadline = time.monotonic() + (self._wake_patience_s if patience_s is None else patience_s)
        speaking_seen = False
        blocks: list[Any] = []
        start_index: int | None = None
        speech_started: float | None = None
        speech_total = 0.0
        while True:
            for block in capture.poll_blocks():
                ws.send(block.tobytes())
                blocks.append(block)
            if len(blocks) > _MAX_KEPT_BLOCKS:
                drop = len(blocks) - _MAX_KEPT_BLOCKS
                del blocks[:drop]
                if start_index is not None:
                    start_index = max(0, start_index - drop)

            message = self._recv_nonblocking(ws)
            if message is not None:
                result = self._handle_message(message)
                if result is not None:
                    if speech_started is not None:
                        speech_total += time.monotonic() - speech_started
                    return self._with_audio(result, blocks, start_index, speech_total)
                if message.get("t") == "vad":
                    now = time.monotonic()
                    if message.get("speaking"):
                        speaking_seen = True
                        if start_index is None:
                            start_index = max(0, len(blocks) - _VAD_LEAD_BLOCKS)
                        if speech_started is None:
                            speech_started = now
                    elif speech_started is not None:
                        speech_total += now - speech_started
                        speech_started = None

            if not speaking_seen and time.monotonic() >= deadline + _GIVE_UP_GRACE_S:
                return self._give_up(ws)

    @staticmethod
    def _with_audio(
        result: SttStreamResult, blocks: list[Any], start_index: int | None, speech_s: float
    ) -> SttStreamResult:
        if result.kind != "final" or start_index is None or start_index >= len(blocks):
            return result
        result.audio = np.concatenate(blocks[start_index:]).astype(np.float32, copy=False)
        result.speech_s = speech_s
        return result

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
            raw = ws.recv(timeout=_FINAL_WAIT_S)
            message = json.loads(raw)
            result = self._handle_message(message)
            if result is not None:
                return result
        except (TimeoutError, ValueError, TypeError, ConnectionClosed):
            pass
        return SttStreamResult(kind="timeout")
