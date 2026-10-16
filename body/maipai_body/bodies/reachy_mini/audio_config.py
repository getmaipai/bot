"""Reachy Mini XVF3800 defaults and nonblocking startup audio setup.

The daemon is the only owner of the microphone array. OS mixer and XMOS
recovery hooks are injected because their availability depends on the body image.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)

XVF3800_CONFIG: dict[str, list[float]] = {
    "PP_AGCMAXGAIN": [10.0],
    "PP_MIN_NS": [0.8],
    "PP_MIN_NN": [0.8],
    "PP_GAMMA_E": [0.5],
    "PP_GAMMA_ETAIL": [0.5],
    "PP_NLATTENONOFF": [0.0],
    "PP_MGSCALE": [4.0, 1.0, 1.0],
}
SILENT_CAPTURE_S = 5.0


class AudioDaemon(Protocol):
    def get_audio_parameter(self, name: str) -> list[float]: ...

    def apply_audio_config(
        self, config: Mapping[str, list[float]], verify: bool = True
    ) -> bool: ...

    def set_microphone_volume(self, volume: int) -> int: ...


class Mixer(Protocol):
    def set_percent(self, control: str, value: int) -> None: ...


@dataclass(frozen=True)
class AudioSetupResult:
    ok: bool
    health: str


class AudioConfigurator:
    """Apply the profile's tuning at every connection without blocking startup."""

    def __init__(
        self,
        daemon: AudioDaemon,
        *,
        mixer: Mixer | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        reboot: Callable[[], None] | None = None,
    ) -> None:
        self._daemon = daemon
        self._mixer = mixer
        self._sleep = sleep
        self._clock = clock
        self._reboot = reboot
        self._zero_since: float | None = None
        self._recovering = False
        self._device_present = True
        self._volume_pending: int | None = None

    def on_connect(self) -> AudioSetupResult:
        self._zero_since = None
        try:
            defaults = {name: self._daemon.get_audio_parameter(name) for name in XVF3800_CONFIG}
            logger.info("XVF3800 defaults: %s", defaults)
            if not self._daemon.apply_audio_config(XVF3800_CONFIG, verify=True):
                raise RuntimeError("daemon did not confirm audio configuration")
            self._sleep(0.1)
            for name, expected in XVF3800_CONFIG.items():
                actual = self._daemon.get_audio_parameter(name)
                if not _values_match(actual, expected):
                    raise RuntimeError(f"XVF3800 verify mismatch for {name}: {actual}")
            self._daemon.set_microphone_volume(100)
            if self._mixer is not None:
                self._mixer.set_percent("PCM", 100)
                self._mixer.set_percent("PCM,1", 100)
            self._device_present = True
            return AudioSetupResult(ok=True, health="ready")
        except Exception as error:
            logger.warning(
                "Reachy Mini audio setup failed; continuing without tuned audio", exc_info=True
            )
            self._device_present = False
            health = "no_audio_device" if _is_missing_device(error) else "audio_config_failed"
            return AudioSetupResult(ok=False, health=health)

    def request_output_volume(self, volume: int) -> None:
        self._volume_pending = max(0, min(100, int(volume)))

    def apply_pending_output_volume(self, *, turn_active: bool) -> bool:
        """Apply volume only at idle, avoiding the daemon's mid-stream silence bug."""
        if turn_active or self._volume_pending is None:
            return False
        try:
            self._daemon.set_output_volume(self._volume_pending)  # type: ignore[attr-defined]
        except Exception:
            logger.warning("Could not set Reachy Mini output volume", exc_info=True)
            return False
        self._volume_pending = None
        return True

    def mark_capture_started(self) -> None:
        """Start or restart the silent-capture watchdog for a fresh stream."""
        self._zero_since = None
        self._recovering = False

    def observe_capture_peak(self, peak: float) -> bool:
        """Recover once after five seconds at zero; caller supplies captured peaks."""
        if peak > 0:
            self._zero_since = None
            return False
        now = self._clock()
        if self._zero_since is None:
            self._zero_since = now
            return False
        if self._recovering or self._reboot is None or now - self._zero_since < SILENT_CAPTURE_S:
            return False
        self._recovering = True
        try:
            self._reboot()
            self._sleep(4.0)
            result = self.on_connect()
            return result.ok
        except Exception:
            logger.warning("XVF3800 recovery failed", exc_info=True)
            return False
        finally:
            self._recovering = False


def _values_match(actual: list[float], expected: list[float]) -> bool:
    return len(actual) == len(expected) and all(abs(a - b) < 1e-6 for a, b in zip(actual, expected))


def _is_missing_device(error: Exception) -> bool:
    text = str(error).lower()
    return "404" in text or "not found" in text or "no audio device" in text
