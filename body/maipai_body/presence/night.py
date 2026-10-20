"""FACE-NIGHT-01: quiet hours and measured-light hysteresis for StackChan."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from maipai_body.presence.sleep_auto import DARK_LUMA
from maipai_body.settings_keys import FACE_COLOR_KEY, NIGHT_MODE_KEY, face_color, night_mode

logger = logging.getLogger("maipai_body.presence.night")

# Pending measurement on the unit. Lux from the sensor beside the display may be biased.
NIGHT_DARK_LUX = 8.0
# Pending measurement on the unit; deliberately above the dark threshold for hysteresis.
NIGHT_LIGHT_LUX = 20.0
STABLE_FOR_S = 120.0
POLL_S = 10.0
# Night volume is this share of the owner's volume (the design says about 40%).
NIGHT_VOLUME_SHARE = 0.4
# Pending measurement on the unit: the dimmed backlight level (0 to 100).
NIGHT_BRIGHTNESS = 15
# Nothing on the unit reads these back, so they are what the Bot last set until told.
DEFAULT_OWNER_VOLUME = 60
DEFAULT_OWNER_BRIGHTNESS = 100
WATCH_LEVEL_KEY = "robot.camera.watch_level"


class NightPolicy:
    """Pure edge policy. Caller supplies monotonic seconds and the current room state."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock = clock
        self.night = False
        self.enabled = True
        self._dark_since: float | None = None
        self._light_since: float | None = None

    def update(
        self,
        *,
        quiet_hours: bool,
        lux: float | None,
        watch_level: str,
        camera_luma: float | None = None,
    ) -> bool:
        now = self.clock()
        if not self.enabled:
            self.night = False
            self._dark_since = self._light_since = None
            return False
        if quiet_hours:
            self.night = True
            self._light_since = None
            return self.night
        if lux is None and watch_level == "off":
            # Nothing may measure the room (no sensor, camera barred), so darkness
            # cannot start night and nothing can confirm light: night then lasts
            # exactly as long as quiet hours.
            self._dark_since = self._light_since = None
            self.night = False
            return False
        # Reuse sleep-auto's camera brightness threshold when the ambient sensor
        # is absent. The luma reader itself enforces watch-level off.
        dark = (
            lux < NIGHT_DARK_LUX
            if lux is not None
            else camera_luma is not None and camera_luma < DARK_LUMA
        )
        light = (
            lux > NIGHT_LIGHT_LUX
            if lux is not None
            else camera_luma is not None and camera_luma >= DARK_LUMA
        )
        if lux is None and camera_luma is None:
            self._dark_since = self._light_since = None
            return self.night
        if not self.night:
            self._light_since = None
            if dark:
                if self._dark_since is None:
                    self._dark_since = now
                if now - self._dark_since >= STABLE_FOR_S:
                    self.night = True
            else:
                self._dark_since = None
        else:
            self._dark_since = None
            if light:
                if self._light_since is None:
                    self._light_since = now
                if now - self._light_since >= STABLE_FOR_S:
                    self.night = False
            else:
                self._light_since = None
        return self.night


class NightDevice(Protocol):
    """The StackChan tool calls the night rule makes (the XiaozhiDeviceClient seam)."""

    def set_face_background(self, palette: str, night: bool) -> object: ...

    def set_idle_motion(self, enabled: bool) -> object: ...

    def get_ambient_light(self) -> float | None: ...

    def set_volume(self, volume: int) -> object: ...

    def set_brightness(self, brightness: int) -> object: ...


class _AlarmVolume:
    """The alarm's Volume seam: writes go straight to the speaker, never scaled."""

    def __init__(self, controller: NightController) -> None:
        self._controller = controller

    def get_level(self) -> int:
        return self._controller.applied_volume

    def set_level(self, level: int) -> None:
        self._controller.write_volume(level)


class NightController:
    """Applies the night rule to a StackChan: polls the light about every 10 s while
    `robot.night.mode` is on, and enters or leaves night on the policy's edges.

    Rule 6 carry (home RULES.md): an alarm or other fixed safety clip is never
    quietened. The alarm raises the volume through `alarm_volume()`; while the alarm
    is active this controller writes no volume, and when it ends the next tick puts
    the volume at the night or day target again."""

    def __init__(
        self,
        device: NightDevice,
        *,
        clock: Callable[[], float],
        quiet_hours: Callable[[], bool],
        watch_level: Callable[[], str] = lambda: "presence",
        camera_luma: Callable[[], float | None] | None = None,
        leds: Callable[[bool], None] | None = None,
        alarm_active: Callable[[], bool] = lambda: False,
    ) -> None:
        self._device = device
        self._quiet = quiet_hours
        self._watch_level = watch_level
        self._camera_luma = camera_luma
        self._leds = leds
        self._alarm_active = alarm_active
        self._policy = NightPolicy(clock)
        self._lock = threading.RLock()
        self.color = "mint"
        self.owner_volume = DEFAULT_OWNER_VOLUME
        self.owner_brightness = DEFAULT_OWNER_BRIGHTNESS
        self.applied_volume = DEFAULT_OWNER_VOLUME
        self.night = False

    @property
    def enabled(self) -> bool:
        return self._policy.enabled

    def alarm_volume(self) -> _AlarmVolume:
        return _AlarmVolume(self)

    def write_volume(self, level: int) -> None:
        self._device.set_volume(level)
        self.applied_volume = level

    # -- settings_changed ------------------------------------------------

    def apply_settings(self, values: Mapping[str, Any]) -> None:
        """Reads `robot.face.color` and `robot.night.mode`; a color change shows now."""
        with self._lock:
            if NIGHT_MODE_KEY in values:
                self._policy.enabled = night_mode(values)
                if not self._policy.enabled:
                    self._policy.update(quiet_hours=False, lux=None, watch_level="off")
                    self._reconcile(False)
            if FACE_COLOR_KEY in values:
                color = face_color(values)
                if color != self.color:
                    self.color = color
                    self._call(self._device.set_face_background, self.color, self.night)

    # -- the poll ----------------------------------------------------------

    def tick(self) -> bool:
        """One poll: read the light (only while night mode is on) and apply any edge."""
        with self._lock:
            if not self._policy.enabled:
                return self.night
            quiet = bool(self._quiet())
            level = self._watch_level()
            lux = None if quiet else self._read_lux()
            luma = None
            if not quiet and lux is None and level != "off" and self._camera_luma is not None:
                luma = self._camera_luma()
            wanted = self._policy.update(
                quiet_hours=quiet, lux=lux, watch_level=level, camera_luma=luma
            )
            self._reconcile(wanted)
            return self.night

    def run(self, stop_event: threading.Event, poll_s: float = POLL_S) -> None:
        while not stop_event.wait(poll_s):
            try:
                self.tick()
            except Exception:
                logger.warning("night poll failed", exc_info=True)

    def _read_lux(self) -> float | None:
        try:
            return self._device.get_ambient_light()
        except Exception:
            return None

    # -- the edges ---------------------------------------------------------

    def _reconcile(self, wanted: bool) -> None:
        if wanted != self.night:
            if not self._edge(wanted):
                return  # the face call failed; the next poll retries
            self.night = wanted
        self._sync_volume()

    def _edge(self, night: bool) -> bool:
        d = self._device
        if not self._call(d.set_face_background, self.color, night):
            return False
        self._call(d.set_brightness, NIGHT_BRIGHTNESS if night else self.owner_brightness)
        if self._leds is not None:
            self._call(self._leds, not night)
        self._call(d.set_idle_motion, not night)
        return True

    def _target_volume(self, night: bool) -> int:
        if not night:
            return self.owner_volume
        return max(0, min(100, round(self.owner_volume * NIGHT_VOLUME_SHARE)))

    def _sync_volume(self) -> None:
        if self._alarm_active():
            return
        target = self._target_volume(self.night)
        if target != self.applied_volume:
            self._call(self.write_volume, target)

    @staticmethod
    def _call(fn: Callable[..., object], *args: object) -> bool:
        try:
            fn(*args)
            return True
        except Exception:
            logger.warning("night call failed", exc_info=True)
            return False
