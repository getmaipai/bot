"""MOTOR-RECOVER-01: the awake gate and the motor bus behind the Reachy Mini client.

Upstream's daemon has no watchdog (pollen-robotics/reachy_mini #589, #1402, #1306,
#1417, #1430): a target sent while a wake or a sleep move runs fights it, a stream
from the sleep pose snaps the head, a servo can latch an input-voltage error and
ignore ``enabled``, and a write to a servo can fail with nothing raised. This module
holds the two seams that make the body safe against that, both injectable so the
suite proves them against fakes with no unit:

* ``MotorBus``: what the body needs from the daemon besides targets (the motor mode,
  the wake and sleep moves, the servo error register and bus voltage, a per-servo
  reboot, a daemon restart). ``DaemonMotorBus`` is the real one.
* ``MotorGate``: wraps the actuator. It drops targets while a wake or sleep runs and
  for 2.2 s after a wake, never streams from the sleep pose (a ``goto`` to neutral
  first), asserts ``enabled`` and reads it back, refuses motion while the servo bus
  reads above 7.0 V (charging), and leaves the body at rest on exit.

UNVERIFIED until the unit (M-R4 and the MOTOR-RECOVER rows of
``docs/dev/measure-runbook.md``): the servo register reads, the bus voltage read and
the per-servo reboot go through the controller's raw channel, whose wire shape the
pinned OpenAPI fixture does not carry. ``DaemonMotorBus`` raises ``NotSupported`` for
them, which the recovery ladder records as a step it could not take.
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from maipai_body.hal.errors import NotSupported
from maipai_body.hal.seam import AntennaPositions, BodyProfile, HeadPose, InterpolationMethod

from .envelope import clamp_target

logger = logging.getLogger("maipai_body.bodies.reachy_mini.motors")

# Upstream #589: a target during a wake move or in the 2.2 s after it fights the
# move and can latch a servo.
WAKE_QUIET_S = 2.2
# The XL330 servos run on 6 to 7 V; the charger lifts the bus above 7.0 V and the
# firmware's behaviour there is unmeasured (M-R4), so no motion until it is cleared.
BUS_VOLTAGE_REFUSE_V = 7.0
# How long a passed enabled or voltage check is trusted, so a 50 Hz stream is not a
# REST call per target.
CHECK_INTERVAL_S = 1.0
NEUTRAL_GOTO_S = 1.0
# Exit: distance-scaled, never a snap and never an endless crawl.
EXIT_RATE_RAD_S = 0.6
EXIT_MIN_S = 1.0
EXIT_MAX_S = 4.0
DAEMON_UNIT = "reachy-mini-daemon.service"
# The line the installer's sudoers file allows (scripts/robot-conf/).
DAEMON_RESTART_COMMAND = ("sudo", "-n", "systemctl", "restart", DAEMON_UNIT)


class MotorBus(Protocol):
    def motor_mode(self) -> str: ...

    def set_motor_mode(self, mode: str) -> None: ...

    def wake_up(self) -> None: ...

    def goto_sleep(self) -> None: ...

    def bus_voltage_v(self) -> float | None:
        """The servo bus voltage in volts, None when it cannot be read."""
        ...

    def error_registers(self) -> dict[str, int]:
        """Each servo's hardware error status (XL330 address 70), by servo name."""
        ...

    def reboot_motor(self, name: str) -> None: ...

    def restart_daemon(self) -> bool:
        """True when the restart was issued, False when it is not permitted here."""
        ...


class DaemonMotorBus:
    """The real bus over the daemon's REST API on the robot itself."""

    def __init__(
        self,
        base_url: str,
        *,
        session: requests.Session | None = None,
        run: Callable[..., Any] = subprocess.run,
        timeout_s: float = 5.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._run = run
        self._timeout = timeout_s

    @classmethod
    def for_client(cls, client: Any) -> DaemonMotorBus:
        return cls(str(client._reachy._daemon_http_url).rstrip("/"))

    def _get(self, path: str) -> Any:
        response = self._session.get(f"{self._base}{path}", timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def _post(self, path: str) -> None:
        response = self._session.post(f"{self._base}{path}", timeout=self._timeout)
        response.raise_for_status()

    def motor_mode(self) -> str:
        return str(self._get("/api/motors/status")["mode"])

    def set_motor_mode(self, mode: str) -> None:
        self._post(f"/api/motors/set_mode/{mode}")

    def wake_up(self) -> None:
        self._post("/api/move/play/wake_up")

    def goto_sleep(self) -> None:
        self._post("/api/move/play/goto_sleep")

    def bus_voltage_v(self) -> float | None:
        return None  # UNVERIFIED: raw register 144 needs the unit

    def error_registers(self) -> dict[str, int]:
        raise NotSupported(
            "servo error registers are read through the controller's raw channel, "
            "which is unverified until the unit",
            part="servo bus",
            capability="raw_register_read",
            fix="run the MOTOR-RECOVER row of docs/dev/measure-runbook.md on the unit",
        )

    def reboot_motor(self, name: str) -> None:
        raise NotSupported(
            "a per-servo reboot goes through the controller's raw channel, "
            "which is unverified until the unit",
            part="servo bus",
            capability="motor_reboot",
            fix="run the MOTOR-RECOVER row of docs/dev/measure-runbook.md on the unit",
        )

    def restart_daemon(self) -> bool:
        try:
            result = self._run(
                list(DAEMON_RESTART_COMMAND), capture_output=True, timeout=30, check=False
            )
        except (OSError, subprocess.SubprocessError):
            logger.warning("daemon restart could not be run", exc_info=True)
            return False
        if result.returncode != 0:
            logger.warning(
                "daemon restart refused (exit %s): sudoers line missing?", result.returncode
            )
            return False
        return True


@dataclass(frozen=True)
class Commanded:
    """The last target the gate let through, and when a ``goto`` of it should have arrived."""

    pose: HeadPose | None
    antennas: AntennaPositions | None
    body_yaw: float | None
    settle_until: float


def _distance_rad(commanded: Commanded | None) -> float:
    if commanded is None:
        return 0.0
    parts = [0.0]
    if commanded.pose is not None:
        parts += [abs(commanded.pose.yaw), abs(commanded.pose.pitch), abs(commanded.pose.roll)]
    if commanded.antennas is not None:
        parts += [abs(commanded.antennas.left), abs(commanded.antennas.right)]
    if commanded.body_yaw is not None:
        parts.append(abs(commanded.body_yaw))
    return max(parts)


class MotorGate:
    """Everything a caller sends to the head goes through here; everything else passes."""

    def __init__(
        self,
        inner: Any,
        bus: MotorBus,
        *,
        clock: Callable[[], float] = time.monotonic,
        start_in_sleep_pose: bool = True,
    ) -> None:
        self._inner = inner
        self._bus = bus
        self._clock = clock
        self._asleep = False
        self._sleep_pose = start_in_sleep_pose
        self._wake_until = float("-inf")
        self._neutral_until = float("-inf")
        self._enabled_ok_until = float("-inf")
        self._voltage_ok_until = float("-inf")
        self._voltage_bad_until = float("-inf")
        self._voltage_bad_v = 0.0
        self._voltage_unknown_logged = False
        self._commanded: Commanded | None = None
        self.dropped_targets = 0
        self.drop_reasons: Counter[str] = Counter()

    def __getattr__(self, name: str) -> Any:
        # Only reached for names the gate does not define: audio, camera, IMU, tracking.
        return getattr(self._inner, name)

    @property
    def profile(self) -> BodyProfile:
        return self._inner.profile

    # -- state read by the health watchdog --

    @property
    def commanded(self) -> Commanded | None:
        return self._commanded

    def motion_expected(self) -> bool:
        """False while a wake, a sleep or a neutral move owns the body."""
        now = self._clock()
        return not self._asleep and now >= self._wake_until and now >= self._neutral_until

    def invalidate_checks(self) -> None:
        """Forget the cached enabled and voltage checks (after a recovery step)."""
        self._enabled_ok_until = float("-inf")
        self._voltage_ok_until = float("-inf")
        self._voltage_bad_until = float("-inf")

    # -- wake and sleep --

    def wake_up(self) -> None:
        self._bus.wake_up()
        self._asleep = False
        self._sleep_pose = False
        self._wake_until = self._clock() + WAKE_QUIET_S
        self._neutral_until = float("-inf")
        self._commanded = None
        self.invalidate_checks()

    def goto_sleep(self) -> None:
        self._bus.goto_sleep()
        self._asleep = True
        self._sleep_pose = True
        self._commanded = None

    # -- the actuator --

    def goto(
        self,
        pose: HeadPose | None = None,
        antennas: AntennaPositions | None = None,
        body_yaw: float | None = None,
        duration_s: float = 0.5,
        method: InterpolationMethod = "minjerk",
    ) -> None:
        clamp_target(self.profile, pose, antennas, body_yaw)
        if not self._admit(streaming=False):
            return
        self._inner.goto(pose, antennas, body_yaw, duration_s, method)
        self._sleep_pose = False
        self._record(pose, antennas, body_yaw, self._clock() + duration_s)

    def set_target(
        self,
        pose: HeadPose | None = None,
        antennas: AntennaPositions | None = None,
        body_yaw: float | None = None,
    ) -> None:
        clamp_target(self.profile, pose, antennas, body_yaw)
        if not self._admit(streaming=True):
            return
        if self._sleep_pose:
            self._go_neutral_first()
            self._drop("neutral_first", "a stream from the sleep pose became a goto to neutral")
            return
        self._inner.set_target(pose, antennas, body_yaw)
        self._record(pose, antennas, body_yaw, self._clock())

    def hold(self) -> None:
        """A stop is never gated."""
        self._inner.hold()

    def enable(self) -> None:
        self._inner.enable()
        self.invalidate_checks()

    def disable(self) -> None:
        self._inner.disable()
        self.invalidate_checks()

    # -- exit --

    def safe_exit(self) -> str | None:
        """Enable the motors and settle at rest. Never sleeps the robot. Returns why it
        did not move, or None when it did."""
        if self._asleep or self._sleep_pose:
            return "asleep"
        try:
            self._ensure_enabled(force=True)
        except Exception:
            logger.warning("exit: could not enable the motors", exc_info=True)
            return "not_enabled"
        if self._voltage_refused():
            return "charging"
        duration = min(
            EXIT_MAX_S, max(EXIT_MIN_S, _distance_rad(self._commanded) / EXIT_RATE_RAD_S)
        )
        self._inner.goto(
            HeadPose(), AntennaPositions(left=0.0, right=0.0), 0.0, duration, "minjerk"
        )
        self._record(
            HeadPose(), AntennaPositions(left=0.0, right=0.0), 0.0, self._clock() + duration
        )
        return None

    # -- internals --

    def _go_neutral_first(self) -> None:
        self._inner.goto(
            HeadPose(), AntennaPositions(left=0.0, right=0.0), 0.0, NEUTRAL_GOTO_S, "minjerk"
        )
        self._sleep_pose = False
        self._neutral_until = self._clock() + NEUTRAL_GOTO_S
        self._record(HeadPose(), AntennaPositions(left=0.0, right=0.0), 0.0, self._neutral_until)

    def _drop(self, reason: str, detail: str) -> None:
        self.dropped_targets += 1
        self.drop_reasons[reason] += 1
        logger.warning("target dropped (%s): %s", reason, detail)

    def _admit(self, *, streaming: bool) -> bool:
        now = self._clock()
        if self._asleep:
            self._drop("asleep", "the robot is asleep")
            return False
        if now < self._wake_until:
            self._drop("waking", "inside the quiet window after a wake")
            return False
        if streaming and now < self._neutral_until:
            self._drop("neutral_first", "the move to neutral is still running")
            return False
        if self._voltage_refused():
            self._drop(
                "charging",
                f"servo bus reads {self._voltage_bad_v:.1f} V, above "
                f"{BUS_VOLTAGE_REFUSE_V:.1f} V (charging); no motion until M-R4 clears it",
            )
            return False
        try:
            self._ensure_enabled()
        except Exception as error:
            self._drop("not_enabled", f"motors would not read back enabled: {error}")
            return False
        return True

    def _ensure_enabled(self, *, force: bool = False) -> None:
        now = self._clock()
        if not force and now < self._enabled_ok_until:
            return
        if self._bus.motor_mode() != "enabled":
            self._bus.set_motor_mode("enabled")
            mode = self._bus.motor_mode()
            if mode != "enabled":
                raise RuntimeError(f"motor_control_mode reads {mode!r} after enabling")
        self._enabled_ok_until = now + CHECK_INTERVAL_S

    def _voltage_refused(self) -> bool:
        now = self._clock()
        if now < self._voltage_bad_until:
            return True
        if now < self._voltage_ok_until:
            return False
        try:
            volts = self._bus.bus_voltage_v()
        except Exception:
            volts = None
        if volts is None:
            if not self._voltage_unknown_logged:
                self._voltage_unknown_logged = True
                logger.warning("servo bus voltage is unreadable; motion is not gated on it")
            self._voltage_ok_until = now + CHECK_INTERVAL_S
            return False
        if volts > BUS_VOLTAGE_REFUSE_V:
            self._voltage_bad_v = volts
            self._voltage_bad_until = now + CHECK_INTERVAL_S
            return True
        self._voltage_ok_until = now + CHECK_INTERVAL_S
        return False

    def _record(
        self,
        pose: HeadPose | None,
        antennas: AntennaPositions | None,
        body_yaw: float | None,
        settle_until: float,
    ) -> None:
        previous = self._commanded
        self._commanded = Commanded(
            pose=pose if pose is not None else (previous.pose if previous else None),
            antennas=antennas
            if antennas is not None
            else (previous.antennas if previous else None),
            body_yaw=body_yaw
            if body_yaw is not None
            else (previous.body_yaw if previous else None),
            settle_until=settle_until,
        )
