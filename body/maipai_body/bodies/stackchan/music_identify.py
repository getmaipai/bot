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
LOG = "StackChan song naming:"
RETRY_CAPTURE_S = 12.0


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
        self._session_running = False
        self._capture_tries = 0
        self._retry_at: float | None = None
        self._lock = threading.Lock()

    def on_session_start(self, now: float) -> None:
        with self._lock:
            if not self._session_running:
                self._capture_tries = 0
                self._retry_at = None
            self._session_running = True
            if self._captured:
                logger.info("%s skipped: capture already pending", LOG)
                return
            self._pending_since = None
            self._request_id = None
        sit = self._hooks.situation()
        setting = self._hooks.setting()
        if setting == "ask":
            logger.info("%s waits for the confirm (setting=ask)", LOG)
            return
        for condition, reason in (
            (setting == "off", "setting=off"),
            (sit.in_turn, "in_turn"),
            (sit.muted, "muted"),
            (bool(sit.full_quiet), "full_quiet"),
            (not sit.connected, "not connected"),
            (sit.offline, "offline"),
        ):
            if condition:
                logger.info("%s skipped: %s", LOG, reason)
                return
        if now - self._last_result < RETRY_S:
            logger.info(
                "%s skipped: retry window has %.1f seconds left",
                LOG,
                RETRY_S - (now - self._last_result),
            )
            return
        self._start_capture(now)

    def _start_capture(self, now: float) -> None:
        try:
            started = self._hooks.call_tool("self.music.capture_clip", {"seconds": 10})
        except Exception as exc:
            logger.warning("%s capture_clip raised %s: %.200s", LOG, type(exc).__name__, str(exc))
            return
        if started is True:
            with self._lock:
                self._captured = True
                self._pending_since = now
                self._capture_tries += 1
                self._retry_at = None
            logger.info(
                "%s capture started: requested 10 seconds (try %d)", LOG, self._capture_tries
            )
        else:
            logger.warning("%s capture_clip declined: %r", LOG, started)

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
        except Exception as exc:
            logger.warning(
                "%s explicit capture_clip raised %s: %.200s",
                LOG,
                type(exc).__name__,
                str(exc),
            )
            started = False
        if started is not True:
            if started is not False:
                logger.warning("%s explicit capture_clip declined: %r", LOG, started)
            self._drop_state()
            return {"listen_song": "refused", "why": "clip capture could not start"}
        return {"listen_song": "started", "why": ""}

    def on_clip_event(self, kind: str, extra: dict, now: float) -> None:
        if kind == "music_clip_cancelled":
            why = extra.get("why") if isinstance(extra, dict) else None
            with self._lock:
                ambient = self._captured and self._request_id is None
                retry = ambient and self._session_running and self._capture_tries < 2
                if retry:
                    self._retry_at = now + RETRY_CAPTURE_S
                    self._captured = False
                    self._pending_since = None
                else:
                    self._pending_since = None
                    self._captured = False
                    self._request_id = None
            logger.info(
                "%s clip cancelled: why=%r%s", LOG, why, "; retry in 12 seconds" if retry else ""
            )
            return
        with self._lock:
            captured = self._captured
        if kind != "music_clip_ready" or not captured:
            logger.info("%s ignored clip event: kind=%s; no capture pending", LOG, kind)
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
                fields = [
                    name
                    for name in ("bytes", "rate", "codec")
                    if name not in extra
                    or (
                        name == "bytes"
                        and (
                            not isinstance(size, int)
                            or isinstance(size, bool)
                            or size < 0
                            or size > MAX_CLIP_BYTES
                        )
                    )
                    or (name == "rate" and extra.get("rate") != 8000)
                    or (name == "codec" and extra.get("codec") != "mulaw")
                ]
                raise ValueError(",".join(fields))
        except Exception as exc:
            logger.warning("%s invalid clip metadata: fields=%s", LOG, str(exc)[:200])
            self._discard_clip()
            return
        with self._lock:
            self._pending_since = now
            request_id = self._request_id
        logger.info("%s clip ready: %d bytes", LOG, size)
        self._spawn(lambda: self._pull_clip(size, now, request_id))

    def _pull_clip(self, size: int, now: float, request_id: str | None = None) -> None:
        encoded = bytearray()
        offset = 0
        reads = 0
        try:
            for _ in range(MAX_READS):
                if len(encoded) >= size:
                    break
                answer = self._hooks.call_tool(
                    "self.music.read_clip", {"offset": offset, "length": READ_SIZE}
                )
                reads += 1
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
        except Exception as exc:
            logger.warning("%s clip read failed: %s: %.200s", LOG, type(exc).__name__, str(exc))
            self._discard_clip()
            return
        logger.info("%s clip read complete: %d bytes in %d reads", LOG, len(encoded), reads)
        try:
            self._hooks.call_tool("self.music.drop_clip", {})
        except Exception as exc:
            logger.warning("%s drop clip failed: %s: %.200s", LOG, type(exc).__name__, str(exc))
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
        except Exception as exc:
            logger.warning("%s identify post raised: %s: %.200s", LOG, type(exc).__name__, str(exc))
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
        if result is None:
            logger.info("%s identify post returned None", LOG)
            return
        if isinstance(result, dict) and result.get("status") in {
            "not_ready",
            "rate_limited",
            "needs_confirm",
            "failed",
        }:
            logger.info(
                "%s Home status=%s reason=%r",
                LOG,
                result.get("status"),
                result.get("reason", result.get("why")),
            )
        if not isinstance(result, dict) or result.get("status") != "matched":
            if not isinstance(result, dict):
                logger.info("%s Home returned an unexpected response", LOG)
            return
        title = result.get("title")
        if not isinstance(title, str) or not title:
            logger.info("%s Home matched without a title", LOG)
            return
        logger.info("%s matched (title shown on the face)", LOG)
        artist = result.get("artist")
        text = f"{title} - {artist}" if isinstance(artist, str) and artist else title
        try:
            self._hooks.call_tool("self.face.song_title", {"text": text[:60]})
        except Exception as exc:
            logger.warning("%s showing title failed: %s: %.200s", LOG, type(exc).__name__, str(exc))
            return

    def _discard_clip(self) -> None:
        try:
            self._hooks.call_tool("self.music.drop_clip", {})
        except Exception as exc:
            logger.warning("%s drop clip failed: %s: %.200s", LOG, type(exc).__name__, str(exc))
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
                waited = now - pending
                self._pending_since = None
                self._captured = False
                retry = (
                    self._request_id is None and self._session_running and self._capture_tries < 2
                )
                self._retry_at = now + RETRY_CAPTURE_S if retry else None
                if not retry:
                    self._request_id = None
            else:
                waited = 0
                retry = False
            due = (
                self._retry_at is not None
                and now >= self._retry_at
                and self._session_running
                and self._capture_tries < 2
            )
            if due:
                self._retry_at = None
            elif self._retry_at is not None and not self._session_running:
                self._retry_at = None
        if expired:
            logger.info(
                "%s the unit never said the clip was ready; waited %.1f seconds%s",
                LOG,
                waited,
                "; retry in 12 seconds" if retry else "",
            )
        if due:
            self._start_capture(now)

    def on_session_end(self) -> None:
        # An explicit request belongs to its ready clip even while Home's turn runs.
        with self._lock:
            explicit_pending = self._request_id is not None
            dropped = self._captured
            self._session_running = False
            self._retry_at = None
        if dropped:
            logger.info("%s session ended: dropped pending capture", LOG)
        if not explicit_pending:
            self._drop_state()
        try:
            self._hooks.call_tool("self.face.song_title", {"text": ""})
        except Exception:
            pass
