"""The names in StackChan's saved Wi-Fi list (firmware patch 023)."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from maipai_body.bodies.stackchan.activity import log_activity

logger = logging.getLogger("maipai_body.bodies.stackchan.wifi_list")

MAX_NETWORKS = 10
MAX_SSID_CHARS = 32
MAX_SSID_BYTES = 32
MAX_PASSWORD_BYTES = 63


def _parse_list(result: object) -> list[Any] | None:
    if isinstance(result, Mapping):
        # Some unit clients wrap tool results in a result/value field.
        for key in ("result", "value", "networks", "saved"):
            value = result.get(key)
            parsed = _parse_list(value)
            if parsed is not None:
                return parsed
        return None
    if isinstance(result, (str, bytes, bytearray)):
        try:
            return _parse_list(json.loads(result))
        except (ValueError, TypeError, UnicodeDecodeError):
            return None
    if isinstance(result, list):
        return result
    return None


def _is_false(result: object) -> bool:
    """A unit tool answers a boolean as False, "false", or a result wrapper around either."""
    if isinstance(result, Mapping):
        for key in ("result", "value", "ok"):
            if key in result:
                return _is_false(result[key])
        return False
    if isinstance(result, (str, bytes, bytearray)):
        text = result.decode("utf-8", "ignore") if not isinstance(result, str) else result
        return text.strip().lower() == "false"
    return result is False


class WifiList:
    """Calls existing unit tools and retains the last readable list for offline reports."""

    def __init__(
        self,
        call: Callable[[str, dict], object],
        *,
        on_changed: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._call = call
        self._on_changed = on_changed or (lambda: None)
        self._clock = clock
        self._saved: list[str] = []
        self._has_saved = False
        self.available = False
        # When the list was last read from the unit (epoch seconds), and what the last change did.
        self.saved_at: float | None = None
        self.last: dict[str, Any] | None = None
        # Bumped by every add, forget and use, so the check-in refreshes the list at once.
        self.change_seq = 0
        self._lock = threading.RLock()

    @property
    def has_saved(self) -> bool:
        """True once a list has been read from the unit (an empty list counts)."""
        return self._has_saved and self.available

    def _record(self, action: str, result: str, name: str = "") -> None:
        """Remember what the last change did, log one word-only line, and ask for a check-in now."""
        self.last = {
            "action": action,
            "result": result,
            "name": name[:MAX_SSID_CHARS],
            "at": self._clock(),
        }
        self.change_seq += 1
        log_activity(f"wifi_{action}", f"result={result}")
        self._on_changed()

    def refresh(self) -> bool:
        """Read the saved list from the unit now; True when it answered."""
        self.saved()
        return self.available

    def note_use_event(self, kind: str) -> None:
        """The unit's answer to a switch: it reached the hub (joined) or went back (reverted)."""
        with self._lock:
            last = self.last
            if not last or last.get("action") != "use" or self._clock() - float(last["at"]) > 600:
                return
            result = (
                "joined"
                if kind == "wifi_use_ok"
                else "reverted"
                if kind == "wifi_use_revert"
                else None
            )
            if result is None:
                return
            self._record("use", result, str(last.get("name") or ""))

    def saved(self) -> list[str]:
        with self._lock:
            try:
                raw = _parse_list(self._call("self.wifi.list_saved", {}))
                if raw is None:
                    self.available = False
                    return list(self._saved) if self._has_saved else []
                names: list[str] = []
                for item in raw:
                    ssid = item.get("ssid") if isinstance(item, Mapping) else None
                    if isinstance(ssid, str) and ssid:
                        names.append(ssid[:MAX_SSID_CHARS])
                    if len(names) == MAX_NETWORKS:
                        break
                self._saved = names
                self._has_saved = True
                self.available = True
                self.saved_at = self._clock()
            except Exception:
                self.available = False
                return list(self._saved) if self._has_saved else []
            return list(self._saved)

    @staticmethod
    def _bytes(value: str) -> int:
        return len(value.encode("utf-8"))

    def add(self, ssid: object, password: object) -> dict[str, str]:
        if not isinstance(ssid, str) or not ssid:
            self._record("add", "refused")
            return {"wifi": "refused", "why": "The network name must not be empty."}
        if self._bytes(ssid) > MAX_SSID_BYTES:
            self._record("add", "refused", ssid)
            return {"wifi": "refused", "why": "The network name must be at most 32 bytes."}
        if not isinstance(password, str) or self._bytes(password) > MAX_PASSWORD_BYTES:
            self._record("add", "refused", ssid)
            return {"wifi": "refused", "why": "The network password must be at most 63 bytes."}

        logger.info("wifi add requested (ssid length class: %s)", "empty" if not ssid else "1-32")
        with self._lock:
            try:
                current = self.saved()
                if not self.available:
                    self._record("add", "unreachable", ssid)
                    return {"wifi": "refused", "why": "The robot could not be reached."}
                if len(current) >= MAX_NETWORKS and ssid not in current:
                    self._record("add", "full", ssid)
                    return {
                        "wifi": "refused",
                        "why": "The robot already holds 10 networks. Forget one first.",
                    }
                result = self._call("self.wifi.add", {"ssid": ssid, "password": password})
                if _is_false(result):
                    self._record("add", "refused", ssid)
                    return {"wifi": "refused", "why": "The unit could not save that network."}
                self._saved = []
                self._has_saved = False
                self.saved()
                self._record("add", "ok", ssid)
                return {"wifi": "saved"}
            except Exception:
                # Never include exception text or tool arguments: either may contain the password.
                logger.warning("wifi add tool call failed")
                self._record("add", "unreachable", ssid if isinstance(ssid, str) else "")
                return {"wifi": "refused", "why": "The robot could not be reached."}

    def forget(self, ssid: object) -> dict[str, str]:
        if not isinstance(ssid, str):
            self._record("forget", "refused")
            return {"wifi": "refused", "why": "That network is not saved on the robot."}
        with self._lock:
            names = self.saved()
            try:
                index = names.index(ssid)
            except ValueError:
                self._record("forget", "refused", ssid)
                return {"wifi": "refused", "why": "That network is not saved on the robot."}
            try:
                result = self._call("self.wifi.forget", {"index": index})
                if _is_false(result):
                    self._record("forget", "refused", ssid)
                    return {"wifi": "refused", "why": "The robot could not forget that network."}
                self._saved = []
                self._has_saved = False
                self.saved()
                self._record("forget", "ok", ssid)
                return {"wifi": "forgotten"}
            except Exception:
                logger.warning("wifi forget tool call failed")
                self._record("forget", "unreachable", ssid)
                return {"wifi": "refused", "why": "The robot could not be reached."}

    def use(self, ssid: object) -> dict[str, str]:
        """Ask the unit to leave its network and join the named saved one now (firmware patch 154).

        The unit holds the choice in memory only, never rewrites its saved list, and goes back by
        itself if the hub is not reached within 3 minutes. Nothing here writes the saved list."""
        if not isinstance(ssid, str) or not ssid:
            self._record("use", "refused")
            return {"wifi": "refused", "why": "Choose one of the robot's saved networks."}
        with self._lock:
            names = self.saved()
            try:
                index = names.index(ssid)
            except ValueError:
                self._record("use", "refused", ssid)
                return {"wifi": "refused", "why": "That network is not saved on the robot."}
            try:
                result = self._call("self.wifi.use_now", {"index": index})
            except Exception:
                logger.warning("wifi use tool call failed")
                self._record("use", "unreachable", ssid)
                return {"wifi": "refused", "why": "The robot could not be reached."}
            if _is_false(result) or _is_not_ok(result):
                self._record("use", "refused", ssid)
                return {"wifi": "refused", "why": "The robot could not switch to that network."}
            self._record("use", "switching", ssid)
            return {"wifi": "switching"}


def _is_not_ok(result: object) -> bool:
    """A unit tool that answers JSON {"ok": false, ...} (possibly as text) is a refusal."""
    if isinstance(result, (str, bytes, bytearray)):
        try:
            result = json.loads(result)
        except (ValueError, TypeError, UnicodeDecodeError):
            return False
    return isinstance(result, Mapping) and result.get("ok") is False


def prefer_tailnet(call: Callable[[str, dict], object], payload: object) -> dict[str, Any]:
    """Ask the unit to prefer its tailnet path to the hub for N minutes (0 is off; patch 153)."""
    minutes = payload.get("minutes") if isinstance(payload, Mapping) else None
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 <= minutes <= 120:
        return {"tailnet": "refused", "why": "Minutes must be a whole number from 0 to 120."}
    try:
        result = call("self.network.prefer_tailnet", {"minutes": minutes})
    except Exception:
        logger.warning("prefer_tailnet tool call failed")
        return {"tailnet": "refused", "why": "The robot could not be reached."}
    if _is_false(result) or _is_not_ok(result):
        return {"tailnet": "refused", "why": "The robot's tailnet is not up yet."}
    return {"tailnet": "off"} if minutes == 0 else {"tailnet": "preferred", "minutes": minutes}
