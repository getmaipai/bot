"""Conservative host-side StackChan firmware update controller."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOG = logging.getLogger("maipai_body.bodies.stackchan.firmware_update")
BACKOFF_S = 6 * 60 * 60
TIMER_GUARD_S = 10 * 60


@dataclass(frozen=True)
class Decision:
    do: bool
    why: str


def _version(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^\s*[vV]?(\d+(?:\.\d+)*)", value)
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:
        return None


def _cmp(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    width = max(len(left), len(right))
    a, b = left + (0,) * (width - len(left)), right + (0,) * (width - len(right))
    return (a > b) - (a < b)


def should_update(now: float, state: Mapping[str, Any]) -> Decision:
    """Pure update gate. State fields deliberately describe policy, not device APIs."""
    unit, target = _version(state.get("unit_version")), _version(state.get("target_version"))
    if unit is None:
        return Decision(False, "unit_version_unknown")
    if target is None:
        return Decision(False, "target_version_invalid")
    if _cmp(unit, target) >= 0:
        return Decision(False, "current_or_newer")
    if state.get("link_healthy") is not True:
        return Decision(False, "link_unhealthy")
    if state.get("in_turn"):
        return Decision(False, "turn_in_progress")
    if state.get("in_call"):
        return Decision(False, "in_call")
    due = state.get("timer_due_in")
    if (
        state.get("timers_unknown")
        or state.get("timer_active")
        or state.get("alarm_active")
        or (isinstance(due, (int, float)) and due <= TIMER_GUARD_S)
    ):
        return Decision(False, "timer_or_alarm")
    if state.get("muted"):
        return Decision(False, "muted")
    if state.get("full_quiet"):
        return Decision(False, "full_quiet")
    percent, charging = state.get("battery_percent"), state.get("charging")
    if charging is not True and (
        isinstance(percent, bool) or not isinstance(percent, int) or percent < 40
    ):
        return Decision(False, "battery_low_or_unknown")
    failed_at = state.get("failed_at")
    if (
        state.get("failed_version") == state.get("target_version")
        and isinstance(failed_at, (int, float))
        and now - failed_at < BACKOFF_S
    ):
        return Decision(False, "failure_backoff")
    if state.get("running"):
        return Decision(False, "already_running")
    setting = state.get("firmware_auto", "on")
    if setting is False or setting == "off":
        return Decision(False, "setting_off")
    return Decision(True, "update_available")


class FirmwareUpdater:
    def __init__(
        self,
        *,
        ask_home: Callable[[], dict | None],
        download: Callable[[Path], object],
        serve_once: Callable[[Path], str],
        call_tool: Callable[[str, dict], object],
        situation: Callable[[], Mapping[str, Any]],
        battery: Callable[[], Mapping[str, Any] | None],
        unit_version: Callable[[], str | None],
        now: Callable[[], float],
        report: Callable[[bool, int | None], object] | None = None,
    ) -> None:
        self.ask_home, self.download, self.serve_once = ask_home, download, serve_once
        self.call_tool, self.situation, self.battery = call_tool, situation, battery
        self.unit_version, self.now = unit_version, now
        self.report = report or (lambda _updating, _progress: None)
        self.running = False
        self.progress: int | None = None
        self.failed_at: float | None = None
        self.failed_version: str | None = None
        self.failure_reason: str | None = None
        self.target_version: str | None = None
        self.firmware_auto = "on"
        # Set when the unit wrote the new image and restarted. Cleared when it reports that version
        # (or the validated event); after 15 minutes without it, a rollback (6 hour backoff).
        self.done_version: str | None = None
        self.done_at: float | None = None

    def apply_settings(self, values: dict) -> None:
        if "robot.firmware.auto" in values:
            self.firmware_auto = values["robot.firmware.auto"]

    def _state(self, answer: Mapping[str, Any] | None = None) -> dict[str, Any]:
        sit = dict(self.situation())
        battery = self.battery()
        if not isinstance(battery, Mapping):
            battery = {}
        sit.update(
            unit_version=self.unit_version(),
            target_version=(answer or {}).get("version"),
            battery_percent=battery.get("percent"),
            charging=battery.get("charging"),
            failed_at=self.failed_at,
            failed_version=self.failed_version,
            running=self.running,
            firmware_auto=self.firmware_auto,
        )
        return sit

    def tick(self, now: float | None = None) -> None:
        now = self.now() if now is None else now
        if self.done_version is not None and self.done_at is not None:
            if self.unit_version() == self.done_version:
                self.done_version = self.done_at = None
            elif now - self.done_at > 900:
                self.failed_at, self.failed_version = now, self.done_version
                self.failure_reason = "rolled_back"
                LOG.info("StackChan firmware update: the unit is not on the new image; backing off")
                self.done_version = self.done_at = None
            else:
                LOG.info("StackChan firmware update: decision skip (awaiting_new_image)")
                return
        if self.running:
            decision = Decision(False, "already_running")
            LOG.info("StackChan firmware update: decision skip (%s)", decision.why)
            return
        try:
            answer = self.ask_home()
            if not isinstance(answer, dict) or answer.get("available") is not True:
                decision = Decision(False, "no_verified_update")
            else:
                self.target_version = answer.get("version")
                decision = should_update(now, self._state(answer))
            LOG.info(
                "StackChan firmware update: decision %s (%s)",
                "run" if decision.do else "skip",
                decision.why,
            )
            if decision.do:
                self._attempt(answer, now)
        except Exception as exc:
            LOG.info("StackChan firmware update: step Home check failed (%s)", type(exc).__name__)

    def _attempt(self, answer: dict, now: float) -> None:
        path: Path | None = None
        self.running = True
        version = answer.get("version")
        try:
            import os
            import tempfile

            fd, name = tempfile.mkstemp(
                prefix="maipai-stackchan-fw-", suffix=".bin", dir=os.environ.get("TMPDIR")
            )
            os.close(fd)
            path = Path(name)
            LOG.info("StackChan firmware update: downloading image")
            self.download(path)
            size = path.stat().st_size
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if size != answer.get("size"):
                raise ValueError("image_size_mismatch")
            if digest.lower() != str(answer.get("sha256", "")).lower():
                raise ValueError("image_hash_mismatch")
            url = self.serve_once(path)
            LOG.info("StackChan firmware update: calling unit update tool")
            self.report(True, None)
            self.call_tool(
                "self.firmware.update",
                {"url": url, "sha256": digest, "size": size, "version": version},
            )
            self.target_version = version
        except Exception as exc:
            self.failed_at, self.failed_version = now, version if isinstance(version, str) else None
            reason = str(exc)
            self.failure_reason = (
                reason
                if reason
                in {
                    "image_size_mismatch",
                    "image_hash_mismatch",
                }
                else type(exc).__name__
            )
            self.running = False
            self.report(False, None)
            LOG.info("StackChan firmware update: attempt failed (%s)", self.failure_reason)
        finally:
            if path is not None:
                path.unlink(missing_ok=True)

    def on_unit_event(self, kind: str, extra: Mapping[str, Any] | None, now: float) -> None:
        extra = extra or {}
        if kind == "firmware_update_started":
            self.running, self.progress = True, 0
            self.report(True, 0)
        elif kind == "firmware_update_progress":
            value = extra.get("percent")
            if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100:
                self.progress = value
                self.report(True, value)
        elif kind in {"firmware_update_done", "firmware_update_failed"}:
            self.running = False
            self.report(False, None)
            if kind == "firmware_update_failed":
                self.failed_at, self.failed_version = now, self.target_version
                reason = extra.get("reason")
                self.failure_reason = (
                    str(reason)[:200] if isinstance(reason, str) else "unit_failed"
                )
            else:
                self.failed_at = self.failed_version = self.failure_reason = None
                self.done_version, self.done_at = self.target_version, now
        elif kind == "firmware_update_validated":
            self.done_version = self.done_at = None
        LOG.info("StackChan firmware update: event %s", kind)
