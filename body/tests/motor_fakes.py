"""A scripted motor bus for the MOTOR-RECOVER-01 suite: the daemon's motor mode,
the servo error registers and bus voltage, with faults a test can plant."""

from __future__ import annotations

from maipai_body.hal.errors import NotSupported


class FakeMotorBus:
    def __init__(self) -> None:
        self.mode = "enabled"
        self.voltage_v: float | None = 6.2
        self.registers: dict[str, int] = {"head_1": 0, "body_yaw": 0}
        self.calls: list[str] = []
        self.registers_readable = True
        self.restart_allowed = True
        # What clears the planted fault: "cycle", "reboot" or "restart"; None = nothing.
        self.fault_cleared_by: str | None = None
        self.faulted = False
        self.refuse_enable_while_faulted = True
        self.reboot_target: str | None = None
        self._cycled = False

    def plant_fault(self, *, cleared_by: str | None, latched: tuple[str, ...] = ()) -> None:
        self.faulted = True
        self.fault_cleared_by = cleared_by
        for name in latched:
            self.registers[name] = 0x01

    def _clear(self, step: str) -> None:
        if self.faulted and self.fault_cleared_by == step:
            self.faulted = False
            for name in self.registers:
                self.registers[name] = 0

    # -- the MotorBus surface --

    def motor_mode(self) -> str:
        self.calls.append("motor_mode")
        return self.mode

    def set_motor_mode(self, mode: str) -> None:
        self.calls.append(f"set_motor_mode:{mode}")
        if mode == "disabled":
            self.mode = mode
            self._cycled = True
            return
        if mode == "enabled" and self.faulted:
            if self.fault_cleared_by == "cycle" and self._cycled:
                self._clear("cycle")
            elif self.refuse_enable_while_faulted:
                self.mode = "disabled"  # the fake ignores `enabled` after a fault
                return
        self.mode = mode
        self._cycled = False

    def wake_up(self) -> None:
        self.calls.append("wake_up")

    def goto_sleep(self) -> None:
        self.calls.append("goto_sleep")

    def bus_voltage_v(self) -> float | None:
        self.calls.append("bus_voltage_v")
        return self.voltage_v

    def error_registers(self) -> dict[str, int]:
        self.calls.append("error_registers")
        if not self.registers_readable:
            raise NotSupported(
                "raw register read is unavailable", part="servo bus", capability="raw_read"
            )
        return dict(self.registers)

    def reboot_motor(self, name: str) -> None:
        self.calls.append(f"reboot_motor:{name}")
        self.reboot_target = name
        self._clear("reboot")

    def restart_daemon(self) -> bool:
        self.calls.append("restart_daemon")
        if not self.restart_allowed:
            return False
        self._clear("restart")
        return True
