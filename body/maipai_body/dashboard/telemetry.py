"""The dashboard's view of a body: the latest state frame plus presence, as one JSON snapshot."""

from __future__ import annotations

import threading
import time
from typing import Any

from maipai_body.hal.errors import BodyLost
from maipai_body.hal.seam import BodyProfile, StateFrame
from maipai_body.presence.arbitration import ArbitrationState, active_priority
from maipai_body.presence.observations import read_presence


class TelemetryPump:
    """Keeps the newest state frame and presence read of one body.

    A background thread drains ``client.state_feed`` (reopening it when it
    ends, so a replayed fixture or a dropped stream does not freeze the
    page) and reads presence beside it. ``BodyLost`` marks the snapshot
    disconnected and stops the thread; nothing here ever commands the body.
    """

    def __init__(
        self,
        client: Any,
        profile: BodyProfile,
        arbitration: ArbitrationState,
        *,
        hz: float = 10.0,
    ) -> None:
        self._client = client
        self._profile = profile
        self._arbitration = arbitration
        self._hz = hz
        self._lock = threading.Lock()
        self._frame: StateFrame | None = None
        self._presence: dict[str, Any] | None = None
        self._connected = True
        self._muted = False
        self._last_outcome: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="dashboard-telemetry", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def mark_lost(self) -> None:
        with self._lock:
            self._connected = False

    def set_muted(self, muted: bool) -> None:
        with self._lock:
            self._muted = muted

    def record_outcome(self, outcome: dict[str, Any]) -> None:
        with self._lock:
            self._last_outcome = outcome

    def latest_doa_angle(self) -> float:
        with self._lock:
            frame = self._frame
        if frame is not None and frame.doa is not None:
            return frame.doa.angle_rad
        return 0.0

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            frame, presence = self._frame, self._presence
            connected, muted, outcome = self._connected, self._muted, self._last_outcome
        dump = (lambda m: m.model_dump()) if frame is not None else (lambda m: None)
        return {
            "body": self._profile.id,
            "connected": connected,
            "seq": frame.seq if frame is not None else None,
            "age_ms": (
                round((time.monotonic_ns() - frame.t_received_ns) / 1e6, 1)
                if frame is not None
                else None
            ),
            "head_pose": dump(frame.head_pose) if frame and frame.head_pose else None,
            "antennas": dump(frame.antennas) if frame and frame.antennas else None,
            "body_yaw": frame.body_yaw if frame is not None else None,
            "doa": dump(frame.doa) if frame and frame.doa else None,
            "presence": presence,
            "arbitration": {
                "priority": active_priority(self._arbitration).name,
                "stop": self._arbitration.stop_active,
                "service": self._arbitration.service_active,
                "tracking": self._arbitration.tracking_active,
                "expression": self._arbitration.expression_active,
            },
            "muted": muted,
            "last_outcome": outcome,
        }

    def _read_presence(self) -> dict[str, Any] | None:
        try:
            return read_presence(self._client).model_dump()
        except BodyLost:
            raise
        except Exception:  # a sensor this body lacks must not blind the pose readout
            return None

    def _run(self) -> None:
        period = 1.0 / self._hz
        try:
            while not self._stop.is_set():
                got_any = False
                feed = self._client.state_feed(self._hz)
                try:
                    for frame in feed:
                        got_any = True
                        presence = self._read_presence()
                        with self._lock:
                            self._frame, self._presence = frame, presence
                        if self._stop.wait(period):
                            return
                finally:
                    feed.close()
                if not got_any and self._stop.wait(period):
                    return
        except BodyLost:
            self.mark_lost()
