"""The names in StackChan's saved Wi-Fi list (firmware patch 023)."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Mapping
from typing import Any

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
    ) -> None:
        self._call = call
        self._on_changed = on_changed or (lambda: None)
        self._saved: list[str] = []
        self._has_saved = False
        self.available = False
        self._lock = threading.RLock()

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
            except Exception:
                self.available = False
                return list(self._saved) if self._has_saved else []
            return list(self._saved)

    @staticmethod
    def _bytes(value: str) -> int:
        return len(value.encode("utf-8"))

    def add(self, ssid: object, password: object) -> dict[str, str]:
        if not isinstance(ssid, str) or not ssid:
            return {"wifi": "refused", "why": "The network name must not be empty."}
        if self._bytes(ssid) > MAX_SSID_BYTES:
            return {"wifi": "refused", "why": "The network name must be at most 32 bytes."}
        if not isinstance(password, str) or self._bytes(password) > MAX_PASSWORD_BYTES:
            return {"wifi": "refused", "why": "The network password must be at most 63 bytes."}

        logger.info("wifi add requested (ssid length class: %s)", "empty" if not ssid else "1-32")
        with self._lock:
            try:
                current = self.saved()
                if not self.available:
                    return {"wifi": "refused", "why": "The robot could not be reached."}
                if len(current) >= MAX_NETWORKS and ssid not in current:
                    return {
                        "wifi": "refused",
                        "why": "The robot already holds 10 networks. Forget one first.",
                    }
                result = self._call("self.wifi.add", {"ssid": ssid, "password": password})
                if _is_false(result):
                    return {"wifi": "refused", "why": "The unit could not save that network."}
                self._refresh_after_change()
                return {"wifi": "saved"}
            except Exception:
                # Never include exception text or tool arguments: either may contain the password.
                logger.warning("wifi add tool call failed")
                return {"wifi": "refused", "why": "The robot could not be reached."}

    def forget(self, ssid: object) -> dict[str, str]:
        if not isinstance(ssid, str):
            return {"wifi": "refused", "why": "That network is not saved on the robot."}
        with self._lock:
            names = self.saved()
            try:
                index = names.index(ssid)
            except ValueError:
                return {"wifi": "refused", "why": "That network is not saved on the robot."}
            try:
                result = self._call("self.wifi.forget", {"index": index})
                if _is_false(result):
                    return {"wifi": "refused", "why": "The robot could not forget that network."}
                self._refresh_after_change()
                return {"wifi": "forgotten"}
            except Exception:
                logger.warning("wifi forget tool call failed")
                return {"wifi": "refused", "why": "The robot could not be reached."}

    def _refresh_after_change(self) -> None:
        self._saved = []
        self._has_saved = False
        self.saved()
        self._on_changed()
