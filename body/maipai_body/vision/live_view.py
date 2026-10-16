"""LIVE-VIEW-01 (bot half): the JPEG stream to the hub.

``live_view_start {view_id, fps, size}`` makes the robot post one JPEG every
200 ms to ``/api/devices/me/stream/{view_id}`` until the first of:
``live_view_stop``, the 10 minute cap, a command channel drop, a refusal from
the hub (the view is unknown), the body being held, or an alarm. Every frame is
read through the Eyes tap, which raises the camera cue before the read, and the
director holds that cue for longer than the frame period, so the Eyes stay cyan
for the whole stream. Frames are held in memory for one post and never stored.

The JPEG is what the daemon serves; this module does not resize it to 640x360
(UNVERIFIED: the daemon's size on the unit is not measured).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("maipai_body.vision.live_view")

FRAME_PERIOD_S = 0.2  # 5 fps
MAX_STREAM_S = 600.0
MAX_FRAME_BYTES = 512 * 1024
_MAX_POST_FAILURES = 5


class LiveViewStreamer:
    def __init__(
        self,
        *,
        camera: Any,
        post_frame: Callable[[str, bytes], int],
        refusal: Callable[[], str | None],
        connected: Callable[[], bool],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._camera = camera
        self._post_frame = post_frame
        self._refusal = refusal
        self._connected = connected
        self._clock = clock
        self._lock = threading.Lock()
        self._view_id: str | None = None
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None

    @property
    def streaming(self) -> bool:
        with self._lock:
            return self._view_id is not None

    # -- command handlers (channel thread) ---------------------------------

    def start(self, payload: dict) -> dict:
        view_id = payload.get("view_id")
        if not isinstance(view_id, str) or not view_id:
            raise ValueError("live_view_start requires a view_id")
        reason = self._refusal()
        if reason is not None:
            return {"live_view": "refused", "reason": reason}
        self._halt()  # one view per robot: a new start replaces the old one
        stop = threading.Event()
        thread = threading.Thread(
            target=self._run, args=(view_id, stop), name="live-view", daemon=True
        )
        with self._lock:
            self._view_id, self._stop, self._thread = view_id, stop, thread
        thread.start()
        return {"live_view": "streaming"}

    def stop(self, payload: dict) -> dict:
        view_id = payload.get("view_id")
        with self._lock:
            current = self._view_id
        if current is not None and (view_id is None or view_id == current):
            self._halt()
        return {"live_view": "stopped"}

    def on_channel_drop(self) -> None:
        """A lost command channel ends the view at once (inside one heartbeat)."""
        self._halt()

    def _halt(self) -> None:
        with self._lock:
            stop, thread = self._stop, self._thread
            self._view_id = self._stop = self._thread = None
        if stop is not None:
            stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    # -- the stream thread ------------------------------------------------

    def _run(self, view_id: str, stop: threading.Event) -> None:
        started = self._clock()
        failures = 0
        try:
            while not stop.is_set():
                tick = self._clock()
                if tick - started >= MAX_STREAM_S:
                    break
                if not self._connected() or self._refusal() is not None:
                    break
                try:
                    jpeg = self._camera.get_frame_jpeg()  # the tap raises the cyan cue first
                except Exception:
                    logger.warning("live view frame read failed", exc_info=True)
                    break
                if jpeg and len(jpeg) <= MAX_FRAME_BYTES:
                    try:
                        status = self._post_frame(view_id, bytes(jpeg))
                    except Exception:
                        status = 0
                    if status in (401, 403, 404):
                        break  # the hub does not know this view: stop streaming
                    failures = failures + 1 if status >= 400 or status == 0 else 0
                    if failures >= _MAX_POST_FAILURES:
                        break
                stop.wait(max(0.0, FRAME_PERIOD_S - (self._clock() - tick)))
        finally:
            with self._lock:
                if self._stop is stop:
                    self._view_id = self._stop = self._thread = None
