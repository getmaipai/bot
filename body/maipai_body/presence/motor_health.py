"""MOTOR-RECOVER-01: the position-change watchdog and the recovery ladder.

Upstream has no motor watchdog (reachy_mini #589, #1402, #1306, #1417, #1430): a
servo can latch an input-voltage error, ignore ``enabled`` and report nothing. This
compares what the gate last commanded with what the body reports; when the present
pose does not follow for ``STUCK_AFTER_S`` with no goto still running, it climbs one
rung every ``STUCK_AFTER_S`` while the error lasts:

1. cycle the motor mode (``disabled`` then ``enabled``);
2. read each servo's error register; a latched input-voltage error is offered for a
   per-motor reboot through the hub's card, which runs only on ``confirm_reboot`` and
   never while a person may be touching the head;
3. restart the daemon through the installer's sudoers line (right away when no servo
   is latched, after ``OFFER_TIMEOUT_S`` of silence otherwise);
4. raise one unresolved Repair if the body still does not follow.

A recovery at any rung raises a resolved Repair naming the step that helped. The
ladder runs once per episode, never in a loop. Pure logic: the bus, the clock and the
pose readers are injected.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from maipai_body.bodies.reachy_mini.motors import Commanded, MotorBus
from maipai_body.hal.seam import AntennaPositions, HeadPose

logger = logging.getLogger("maipai_body.presence.motor_health")

STUCK_AFTER_S = 2.0
FOLLOW_TOLERANCE_RAD = 0.1
OFFER_TIMEOUT_S = 60.0
# XL330 hardware error status (address 70): bit 0 is the input voltage error.
INPUT_VOLTAGE_ERROR = 0x01

_ACTIONS = ("cycle", "reboot", "daemon_restart")


@dataclass(frozen=True)
class PresentPose:
    pose: HeadPose | None
    antennas: AntennaPositions | None
    body_yaw: float | None


class MotorHealthLike(Protocol):
    def tick(self, *, held: bool = False) -> None: ...

    def status(self) -> dict[str, Any]: ...

    def confirm_reboot(self, name: str, *, person_touching: bool = False) -> bool: ...


def follow_error_rad(commanded: Commanded, present: PresentPose) -> float:
    """The largest angular gap between the commanded and the present pose, on the axes commanded."""
    gaps = [0.0]
    if commanded.pose is not None and present.pose is not None:
        gaps += [
            abs(commanded.pose.yaw - present.pose.yaw),
            abs(commanded.pose.pitch - present.pose.pitch),
            abs(commanded.pose.roll - present.pose.roll),
        ]
    if commanded.antennas is not None and present.antennas is not None:
        gaps += [
            abs(commanded.antennas.left - present.antennas.left),
            abs(commanded.antennas.right - present.antennas.right),
        ]
    if commanded.body_yaw is not None and present.body_yaw is not None:
        gaps.append(abs(commanded.body_yaw - present.body_yaw))
    return max(gaps)


class MotorHealth:
    def __init__(
        self,
        bus: MotorBus,
        *,
        commanded: Callable[[], Commanded | None],
        present: Callable[[], PresentPose | None],
        clock: Callable[[], float] = time.monotonic,
        on_offer: Callable[[list[str]], None] | None = None,
        on_repair: Callable[[dict[str, Any]], None] | None = None,
        after_step: Callable[[], None] | None = None,
    ) -> None:
        self._bus = bus
        self._commanded = commanded
        self._present = present
        self._clock = clock
        self._on_offer = on_offer
        self._on_repair = on_repair
        self._after_step = after_step
        self._lock = threading.Lock()
        self._reset()

    def _reset(self) -> None:
        self._stage = "healthy"
        self._mismatch_since: float | None = None
        self._step_at = 0.0
        self._offer_at = 0.0
        self._tried: list[str] = []
        self._latched: list[str] = []

    # -- what the state frame carries --

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"motors_latched": list(self._latched), "motors_stuck": self._stage != "healthy"}

    # -- the watchdog --

    def tick(self, *, held: bool = False) -> None:
        now = self._clock()
        with self._lock:
            commanded = self._commanded()
            if held or commanded is None or now < commanded.settle_until:
                self._mismatch_since = None
                return
            present = self._present()
            if present is None:
                return
            if follow_error_rad(commanded, present) <= FOLLOW_TOLERANCE_RAD:
                self._mismatch_since = None
                if self._stage != "healthy":
                    self._recovered()
                return
            if self._mismatch_since is None:
                self._mismatch_since = now
            if self._stage == "healthy":
                if now - self._mismatch_since >= STUCK_AFTER_S:
                    self._stage = "stuck"
                    self._cycle(now)
                return
            self._escalate(now)

    # -- the ladder --

    def _escalate(self, now: float) -> None:
        if self._stage == "offered":
            if now - self._offer_at >= OFFER_TIMEOUT_S:
                self._restart(now)
            return
        if self._stage == "failed" or now - self._step_at < STUCK_AFTER_S:
            return
        if self._stage == "cycled":
            self._read_registers(now)
        elif self._stage == "rebooted":
            self._restart(now)
        elif self._stage == "restarted":
            self._fail()

    def _cycle(self, now: float) -> None:
        self._tried.append("cycle")
        self._stage = "cycled"
        self._step_at = now
        try:
            self._bus.set_motor_mode("disabled")
            self._bus.set_motor_mode("enabled")
        except Exception:
            logger.warning("motor mode cycle failed", exc_info=True)
        self._stepped()

    def _read_registers(self, now: float) -> None:
        try:
            registers = self._bus.error_registers()
        except Exception:
            logger.warning("servo error registers could not be read", exc_info=True)
            self._tried.append("registers_unavailable")
            self._restart(now)
            return
        self._tried.append("registers")
        latched = sorted(n for n, v in registers.items() if v & INPUT_VOLTAGE_ERROR)
        if not latched:
            self._restart(now)
            return
        self._latched = latched
        self._stage = "offered"
        self._offer_at = now
        logger.warning(
            "servo input-voltage error latched on %s; reboot offered to the hub", latched
        )
        if self._on_offer is not None:
            self._on_offer(list(latched))

    def confirm_reboot(self, name: str, *, person_touching: bool = False) -> bool:
        """The hub's command. Never silent, never while a person may be touching the head."""
        with self._lock:
            if person_touching or self._stage != "offered" or name not in self._latched:
                return False
            now = self._clock()
            try:
                self._bus.reboot_motor(name)
                self._bus.set_motor_mode("enabled")
            except Exception:
                logger.warning("reboot of %s failed", name, exc_info=True)
                return False
            self._tried.append("reboot")
            self._stage = "rebooted"
            self._step_at = now
            self._stepped()
            return True

    def _restart(self, now: float) -> None:
        try:
            issued = self._bus.restart_daemon()
        except Exception:
            logger.warning("daemon restart failed", exc_info=True)
            issued = False
        self._step_at = now
        if not issued:
            self._tried.append("daemon_restart_refused")
            self._fail()
            return
        self._tried.append("daemon_restart")
        self._stage = "restarted"
        self._stepped()

    def _stepped(self) -> None:
        if self._after_step is not None:
            try:
                self._after_step()
            except Exception:
                logger.warning("recovery step hook failed", exc_info=True)

    def _fail(self) -> None:
        self._stage = "failed"
        self._repair(resolved=False, helped=None)

    def _recovered(self) -> None:
        actions = [t for t in self._tried if t in _ACTIONS]
        if actions:
            self._repair(resolved=True, helped=actions[-1])
        self._reset()

    def _repair(self, *, resolved: bool, helped: str | None) -> None:
        record = {
            "kind": "motors",
            "resolved": resolved,
            "helped": helped,
            "tried": list(self._tried),
            "latched": list(self._latched),
        }
        logger.warning("motor repair: %s", record)
        if self._on_repair is not None:
            self._on_repair(record)
