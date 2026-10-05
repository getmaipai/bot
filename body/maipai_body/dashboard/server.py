"""The dashboard's stdlib HTTP server: a page, a JSON API, and a server-sent-event feed."""

from __future__ import annotations

import json
import math
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from maipai_body import expression as _expression  # noqa: F401  (registers every body's renderer)
from maipai_body.expression.cue import Cue, Phase
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.expression.primitives import PRIMITIVE_NAMES
from maipai_body.expression.suppression import SuppressionContext
from maipai_body.hal.errors import BodyLost, NotSupported, OutOfEnvelope
from maipai_body.hal.seam import BodyProfile
from maipai_body.presence.arbitration import ArbitrationState

from .telemetry import TelemetryPump

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
# The only files served: the link page's own index.html is not one of them.
ASSETS = {
    "/": ("dashboard.html", "text/html; charset=utf-8"),
    "/static/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
    "/static/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
}

# One cue per cue-mapped primitive; breathe and track are not cue-mapped
# (scripted_source.py), so they take the renderer column directly.
_CUES: dict[str, dict[str, Any]] = {
    "listen": {"phase": Phase.HEARD},
    "glance": {"phase": Phase.SIGNAL, "has_target": True},
    "tilt": {"phase": Phase.SIGNAL, "primary_act": "question"},
    "nod": {"phase": Phase.SIGNAL, "primary_act": "inform"},
    "perk": {"phase": Phase.SIGNAL, "expressed_emotion": "happiness", "emotion_intensity": "high"},
    "attend": {"phase": Phase.SIGNAL, "expressed_emotion": "sadness"},
    "settle": {"phase": Phase.DONE},
    "speak": {"phase": Phase.SPEAK},
    "stop": {"phase": Phase.CANCEL},
}
_DIRECT = ("breathe", "track")


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    # -- plumbing --

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: object) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _same_origin(self) -> bool:
        """Refuse a page from another origin and a rebound hostname.

        A browser tab on any site can POST to a localhost server; this
        moves a body, so the request must name this server as both Host
        and (when sent) Origin, and carry JSON, which a cross-origin form
        cannot.
        """
        host = self.headers.get("Host", "")
        if host.rsplit(":", 1)[0] not in self.server.allowed_hosts:
            return False
        origin = self.headers.get("Origin")
        return origin is None or urlsplit(origin).netloc == host

    # -- routes --

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path in ASSETS:
            name, content_type = ASSETS[path]
            self._send(HTTPStatus.OK, (STATIC_DIR / name).read_bytes(), content_type)
        elif path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/api/state":
            self._json(HTTPStatus.OK, self.server.pump.snapshot())
        elif path == "/api/primitives":
            self._json(
                HTTPStatus.OK,
                {"body": self.server.profile.id, "primitives": list(PRIMITIVE_NAMES)},
            )
        elif path == "/events":
            self._stream()
        else:
            self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._same_origin():
            return self._error(HTTPStatus.FORBIDDEN, "cross-origin request refused")
        if self.headers.get_content_type() != "application/json":
            return self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "send application/json")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
        except ValueError as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))

        path = urlsplit(self.path).path
        try:
            if path == "/api/muted":
                muted = body.get("muted")
                if not isinstance(muted, bool):
                    return self._error(HTTPStatus.BAD_REQUEST, "muted must be true or false")
                return self._json(HTTPStatus.OK, self.server.set_muted(muted))
            prefix = "/api/primitive/"
            if path.startswith(prefix) and path[len(prefix) :] in PRIMITIVE_NAMES:
                direction = body.get("direction_rad")
                if direction is not None and (
                    isinstance(direction, bool) or not isinstance(direction, int | float)
                ):
                    return self._error(HTTPStatus.BAD_REQUEST, "direction_rad must be a number")
                if direction is not None and not math.isfinite(direction):
                    return self._error(HTTPStatus.BAD_REQUEST, "direction_rad must be finite")
                outcome = self.server.render(path[len(prefix) :], direction)
                return self._json(HTTPStatus.OK, outcome)
        except BodyLost as error:
            self.server.pump.mark_lost()
            return self._error(HTTPStatus.SERVICE_UNAVAILABLE, f"body lost: {error}")
        except OutOfEnvelope as error:
            return self._error(HTTPStatus.UNPROCESSABLE_ENTITY, str(error))
        except NotSupported as error:
            return self._error(HTTPStatus.NOT_IMPLEMENTED, str(error))
        self._error(HTTPStatus.NOT_FOUND, "not found")

    def _stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        stopping = self.server.stopping
        try:
            while not stopping.is_set():
                data = json.dumps(self.server.pump.snapshot())
                self.wfile.write(f"data: {data}\n\n".encode())
                self.wfile.flush()
                stopping.wait(self.server.event_period_s)
        except (BrokenPipeError, ConnectionResetError):
            pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], dashboard: DashboardServer) -> None:
        super().__init__(address, _Handler)
        self._dashboard = dashboard
        self.allowed_hosts = {address[0], "localhost", "127.0.0.1"}

    def __getattr__(self, name: str) -> Any:
        if name == "_dashboard":
            raise AttributeError(name)
        return getattr(self._dashboard, name)


class DashboardServer:
    """Serves one body's live state and primitive buttons over HTTP on ``host:port``.

    ``port=0`` picks a free port (read ``.port`` after construction).
    ``client`` is whatever the body's HAL seam gives: the actuator,
    state-feed and presence protocols, never a vendor type.
    """

    def __init__(
        self,
        client: Any,
        profile: BodyProfile,
        *,
        host: str = "127.0.0.1",
        port: int = 8050,
        state_hz: float = 10.0,
    ) -> None:
        self.client = client
        self.profile = profile
        self.engine = ExpressionEngine(client, profile)
        # The dashboard is the expression driver here: tracking and service
        # are not its to claim, so only the expression flag is ever set.
        self.arbitration = ArbitrationState(expression_active=True)
        self.pump = TelemetryPump(client, profile, self.arbitration, hz=state_hz)
        self.stopping = threading.Event()
        self.event_period_s = 1.0 / state_hz
        self._muted = False
        self._cue_seq = 0
        self._lock = threading.Lock()
        self._httpd = _Server((host, port), self)
        self._thread = threading.Thread(
            target=lambda: self._httpd.serve_forever(poll_interval=0.05),
            name="dashboard-http",
            daemon=True,
        )

    @property
    def host(self) -> str:
        return self._httpd.server_address[0]

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def start(self) -> None:
        self.pump.start()
        self._thread.start()

    def stop(self) -> None:
        self.stopping.set()
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)
        self.pump.stop()

    def _context(self) -> SuppressionContext:
        return SuppressionContext(muted=self._muted)

    def _next_seq(self) -> int:
        with self._lock:
            self._cue_seq += 1
            return self._cue_seq

    def render(self, primitive: str, direction_rad: float | None) -> dict[str, Any]:
        """Render one primitive by name and report what the engine did with it."""
        direction = float(direction_rad) if direction_rad is not None else None
        live_doa = self.pump.latest_doa_angle()
        if primitive in _DIRECT:
            result = self.engine.render_primitive(
                primitive,
                self._context(),
                doa_angle_rad=live_doa,
                target_direction_rad=direction,
                cue_seq=self._next_seq(),
            )
        else:
            cue = Cue(cue_seq=self._next_seq(), target_direction_rad=direction, **_CUES[primitive])
            result = self.engine.handle(cue, self._context(), doa_angle_rad=live_doa)
        outcome = {
            "primitive": result.primitive,
            "rendered": result.rendered,
            "suppressed_reason": result.suppressed_reason,
            "rendered_primitive": result.rendered_primitive,
        }
        self.pump.record_outcome(outcome)
        return outcome

    def set_muted(self, muted: bool) -> dict[str, Any]:
        result = self.engine.set_muted(muted, self.arbitration)
        if result is not None:
            self._muted = muted
            self.pump.set_muted(muted)
        outcome = {
            "primitive": None,
            "rendered": result is not None and result.rendered,
            "suppressed_reason": None,
            "rendered_primitive": result.rendered_primitive if result else None,
        }
        self.pump.record_outcome(outcome)
        return outcome
