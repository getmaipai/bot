"""Capture and name one short song clip during a StackChan music session."""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from maipai_body.bodies.stackchan.dance import DanceSituation

logger = logging.getLogger("maipai_body.bodies.stackchan.music_identify")
READY_TIMEOUT_S = 25.0
RETRY_S = 600.0
READ_SIZE = 2400
MAX_CLIP_BYTES = 100000
MAX_READS = 60


def _mulaw_table() -> tuple[int, ...]:
    values = []
    for value in range(256):
        value = ~value & 0xFF
        magnitude = ((value & 0x0F) << 3) + 0x84
        magnitude <<= (value & 0x70) >> 4
        sample = 0x84 - magnitude if value & 0x80 else magnitude - 0x84
        values.append(max(-32768, min(32767, sample)))
    return tuple(values)


MULAW = _mulaw_table()


def _thread(callback: Callable[[], None]) -> None:
    threading.Thread(target=callback, daemon=True).start()


@dataclass
class MusicIdentifyHooks:
    call_tool: Callable[[str, dict], object]
    post_clip: Callable[..., dict | None]
    situation: Callable[[], DanceSituation]
    setting: Callable[[], str]
    clock: Callable[[], float] = time.monotonic
    spawn: Callable[[Callable[[], None]], object] | None = None


class MusicIdentify:
    def __init__(self, hooks: MusicIdentifyHooks) -> None:
        self._hooks = hooks
        self._spawn = hooks.spawn or _thread
        self._pending_since: float | None = None
        self._last_result = float("-inf")
        self._captured = False
        self._request_id: str | None = None
        self._lock = threading.Lock()

    def on_session_start(self, now: float) -> None:
        with self._lock:
            if self._captured:
                return
            self._pending_since = None
            self._request_id = None
        sit = self._hooks.situation()
        setting = self._hooks.setting()
        if setting == "ask":
            logger.info("song naming waits for the confirm")
            return
        if (
            setting == "off"
            or sit.in_turn
            or sit.muted
            or sit.full_quiet
            or not sit.connected
            or sit.offline
        ):
            return
        if now - self._last_result < RETRY_S:
            return
        try:
            started = self._hooks.call_tool("self.music.capture_clip", {"seconds": 10})
        except Exception:
            return
        if started is True:
            with self._lock:
                self._captured = True
                self._pending_since = now

    def listen_now(self, request_id: str, seconds: int, now: float) -> dict:
        """Capture one explicitly requested clip, independent of ambient naming settings."""
        sit = self._hooks.situation()
        if sit.muted:
            return {"listen_song": "refused", "why": "the robot is muted"}
        if sit.full_quiet:
            return {"listen_song": "refused", "why": "full quiet is on"}
        if not sit.connected or sit.offline:
            return {"listen_song": "refused", "why": "the robot is offline"}
        with self._lock:
            if self._captured:
                return {"listen_song": "refused", "why": "a clip is already in progress"}
            self._captured = True
            self._pending_since = now
            self._request_id = request_id
        try:
            started = self._hooks.call_tool(
                "self.music.capture_clip", {"seconds": max(5, min(15, seconds))}
            )
        except Exception:
            started = False
        if started is not True:
            self._drop_state()
            return {"listen_song": "refused", "why": "clip capture could not start"}
        return {"listen_song": "started", "why": ""}

    def on_clip_event(self, kind: str, extra: dict, now: float) -> None:
        if kind == "music_clip_cancelled":
            self._drop_state()
            return
        with self._lock:
            captured = self._captured
        if kind != "music_clip_ready" or not captured:
            return
        try:
            size = extra["bytes"]
            if (
                not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
                or size > MAX_CLIP_BYTES
                or extra.get("rate") != 8000
                or extra.get("codec") != "mulaw"
            ):
                raise ValueError("invalid clip metadata")
        except Exception:
            self._discard_clip()
            return
        with self._lock:
            self._pending_since = now
            request_id = self._request_id
        self._spawn(lambda: self._pull_clip(size, now, request_id))

    def _pull_clip(self, size: int, now: float, request_id: str | None = None) -> None:
        encoded = bytearray()
        offset = 0
        try:
            for _ in range(MAX_READS):
                if len(encoded) >= size:
                    break
                answer = self._hooks.call_tool(
                    "self.music.read_clip", {"offset": offset, "length": READ_SIZE}
                )
                if isinstance(answer, str):
                    answer = json.loads(answer)
                if not isinstance(answer, dict):
                    raise ValueError("invalid clip read response")
                data = answer["data"]
                count = answer["bytes"]
                eof = answer["eof"]
                if (
                    not isinstance(data, str)
                    or not isinstance(count, int)
                    or isinstance(count, bool)
                ):
                    raise ValueError("invalid clip read fields")
                chunk = base64.b64decode(data, validate=True)
                if count != len(chunk) or len(encoded) + len(chunk) > size:
                    raise ValueError("invalid clip read size")
                encoded.extend(chunk)
                offset += len(chunk)
                if eof is True:
                    break
                if not chunk:
                    raise ValueError("empty clip read")
            else:
                raise ValueError("too many clip reads")
            if len(encoded) > size:
                raise ValueError("clip exceeded advertised size")
        except Exception:
            self._discard_clip()
            return
        try:
            self._hooks.call_tool("self.music.drop_clip", {})
        except Exception:
            pass
        pcm = b"".join(int(MULAW[sample]).to_bytes(2, "little", signed=True) for sample in encoded)
        self._identify(pcm, now, request_id)

    def _identify(self, pcm: bytes, now: float, request_id: str | None = None) -> None:
        result = None
        try:
            result = (
                self._hooks.post_clip(pcm, request_id)
                if request_id is not None
                else self._hooks.post_clip(pcm)
            )
        except Exception:
            return
        finally:
            if request_id is not None:
                with self._lock:
                    if self._request_id == request_id:
                        # No music session ends an explicit request: free the slot.
                        self._request_id = None
                        self._captured = False
                        self._pending_since = None
        self._last_result = now
        if not isinstance(result, dict) or result.get("status") != "matched":
            return
        title = result.get("title")
        if not isinstance(title, str) or not title:
            return
        artist = result.get("artist")
        text = f"{title} - {artist}" if isinstance(artist, str) and artist else title
        try:
            self._hooks.call_tool("self.face.song_title", {"text": text[:60]})
        except Exception:
            return

    def _discard_clip(self) -> None:
        try:
            self._hooks.call_tool("self.music.drop_clip", {})
        except Exception:
            pass
        self._drop_state()

    def _drop_state(self) -> None:
        with self._lock:
            self._pending_since = None
            self._captured = False
            self._request_id = None

    def tick(self, now: float) -> None:
        with self._lock:
            pending = self._pending_since
            expired = pending is not None and now - pending >= READY_TIMEOUT_S
            if expired:
                self._pending_since = None
                self._captured = False
                self._request_id = None

    def on_session_end(self) -> None:
        # An explicit request belongs to its ready clip even while Home's turn runs.
        with self._lock:
            explicit_pending = self._request_id is not None
        if not explicit_pending:
            self._drop_state()
        try:
            self._hooks.call_tool("self.face.song_title", {"text": ""})
        except Exception:
            pass
