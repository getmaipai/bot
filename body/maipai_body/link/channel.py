"""The authenticated Home-to-robot command WebSocket."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from urllib.parse import urlparse

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

logger = logging.getLogger("maipai_body.link.channel")

Handler = Callable[[dict], dict | None]


class CommandChannel:
    """Reconnect, replay and dispatch durable hub commands once per id."""

    def __init__(
        self,
        base_url: str,
        session_cookie: str,
        *,
        handlers: Mapping[str, Handler] | None = None,
        time_handler: Callable[[str], None] | None = None,
        settings_handler: Callable[[dict], None] | None = None,
        on_drop: Callable[[str], None] | None = None,
        credentials: Callable[[], tuple[str, str]] | None = None,
        wall_clock: Callable[[], float] = time.time,
        reconnect_delay_s: float = 1.0,
        connector: Callable = connect,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_cookie = session_cookie
        self.handlers = dict(handlers or {})
        self.last_hub_time: str | None = None
        self.last_settings_change: dict | None = None
        self.handlers.setdefault("time", self._time_command)
        self.handlers.setdefault("settings_changed", self._settings_command)
        self._time_handler = time_handler
        self._settings_handler = settings_handler
        self._on_drop = on_drop
        self._credentials = credentials or (lambda: (self.base_url, self.session_cookie))
        self._wall_clock = wall_clock
        self._reconnect_delay_s = reconnect_delay_s
        self._connect = connector
        self._processed_ids: set[str] = set()
        self.last_event_id: str | None = None

    def _time_command(self, payload: dict) -> None:
        hub_time = payload.get("hub_time")
        if isinstance(hub_time, str):
            self.last_hub_time = hub_time
            if self._time_handler is not None:
                self._time_handler(hub_time)

    def _settings_command(self, payload: dict) -> None:
        self.last_settings_change = dict(payload)
        if self._settings_handler is not None:
            self._settings_handler(payload)

    def _url(self, base_url: str | None = None) -> str:
        parsed = urlparse(base_url or self.base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("hub URL must use HTTP or HTTPS")
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return f"{scheme}://{parsed.netloc}/api/devices/me/events"

    def _headers(self, session_cookie: str | None = None) -> dict[str, str]:
        cookie = self.session_cookie if session_cookie is None else session_cookie
        headers = {"Cookie": f"session={cookie}"}
        if self.last_event_id:
            headers["Last-Event-ID"] = self.last_event_id
        return headers

    def _handle_text(self, raw: str, ws: ClientConnection) -> None:
        try:
            message = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("ignored malformed hub channel message")
            return
        if not isinstance(message, dict):
            logger.warning("ignored non-object hub channel message")
            return
        message_type = message.get("type")
        if message_type == "heartbeat":
            device_time = (
                datetime.fromtimestamp(self._wall_clock(), UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )
            ws.send(json.dumps({"type": "heartbeat", "device_time": device_time}))
            return
        if message_type != "device-command":
            return
        event_id = message.get("id")
        kind = message.get("kind")
        payload = message.get("payload", {})
        if not isinstance(event_id, str) or not event_id or not isinstance(kind, str):
            logger.warning("ignored hub command without an id or kind")
            return
        response_state = None
        if event_id not in self._processed_ids:
            handler = self.handlers.get(kind)
            if handler is not None:
                try:
                    response_state = handler(payload if isinstance(payload, dict) else {})
                except Exception:
                    logger.warning("hub command %s failed", kind, exc_info=True)
                    return
            # Record before sending the ack so an interrupted ack cannot
            # repeat a successful side effect when the event is replayed.
            self._processed_ids.add(event_id)
        ack = {"type": "ack", "id": event_id}
        if response_state:
            ack["state"] = response_state
        ws.send(json.dumps(ack))
        self.last_event_id = event_id

    def _receive(self, ws: ClientConnection, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                message = ws.recv(timeout=0.5)
            except TimeoutError:
                continue
            if not isinstance(message, str):
                continue
            self._handle_text(message, ws)

    def run(self, stop_event: threading.Event) -> None:
        delay = self._reconnect_delay_s
        while not stop_event.is_set():
            try:
                base_url, session_cookie = self._credentials()
                with self._connect(
                    self._url(base_url),
                    additional_headers=self._headers(session_cookie),
                    open_timeout=10,
                    close_timeout=2,
                    ping_interval=None,
                ) as ws:
                    delay = self._reconnect_delay_s
                    self._receive(ws, stop_event)
            except (ConnectionClosed, OSError, TimeoutError, ValueError) as exc:
                if not stop_event.is_set():
                    logger.info("hub command channel reconnecting after %s", type(exc).__name__)
                    if self._on_drop is not None:
                        try:
                            self._on_drop(f"command channel lost: {type(exc).__name__}")
                        except Exception:
                            logger.warning("command channel drop callback failed", exc_info=True)
            except Exception:
                if not stop_event.is_set():
                    logger.warning("hub command channel failed", exc_info=True)
                    if self._on_drop is not None:
                        try:
                            self._on_drop("command channel failed")
                        except Exception:
                            logger.warning("command channel drop callback failed", exc_info=True)
            stop_event.wait(delay)
            delay = min(max(delay * 2, self._reconnect_delay_s), 30.0)
