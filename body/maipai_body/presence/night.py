"""FACE-NIGHT-01: quiet hours and measured-light hysteresis for StackChan."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from maipai_body.bodies.stackchan.owner_levels import OwnerLevels
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
DEFAULT_OWNER_VOLUME = 70
DEFAULT_OWNER_BRIGHTNESS = 100
UNREADABLE_LIGHT_GRACE_S = 600.0
WATCH_LEVEL_KEY = "robot.camera.watch_level"


class NightPolicy:
    """Pure edge policy. Caller supplies monotonic seconds and the current room state."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock = clock
        self.night = False
        self.enabled = True
        self._dark_since: float | None = None
        self._light_since: float | None = None
        self._unreadable_since: float | None = None

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
            self._unreadable_since = None
            return False
        if quiet_hours:
            self.night = True
            self._light_since = None
            self._unreadable_since = None
            return self.night
        if lux is None and watch_level == "off":
            # Nothing may measure the room (no sensor, camera barred), so darkness
            # cannot start night and nothing can confirm light: night then lasts
            # exactly as long as quiet hours.
            self._dark_since = self._light_since = None
            self.night = False
            self._unreadable_since = None
            return False
        if lux is None and camera_luma is None:
            self._dark_since = self._light_since = None
            if self.night:
                if self._unreadable_since is None:
                    self._unreadable_since = now
                elif now - self._unreadable_since >= UNREADABLE_LIGHT_GRACE_S:
                    self.night = False
                    self._unreadable_since = None
            else:
                self._unreadable_since = None
                self.night = False
            return self.night
        self._unreadable_since = None
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
        levels: OwnerLevels | None = None,
        connected: Callable[[], bool] | None = None,
    ) -> None:
        self._device = device
        self._quiet = quiet_hours
        self._watch_level = watch_level
        self._camera_luma = camera_luma
        self._leds = leds
        self._alarm_active = alarm_active
        self._levels = levels
        self._connected = connected
        self._clock = clock
        self._policy = NightPolicy(clock)
        self._lock = threading.RLock()
        self.color = "mint"
        self._owner_volume = DEFAULT_OWNER_VOLUME
        self._owner_brightness = DEFAULT_OWNER_BRIGHTNESS
        self.applied_volume = DEFAULT_OWNER_VOLUME
        self.night = False
        self.night_volume_override: int | None = None
        self.night_brightness_override: int | None = None
        self._synced = True
        # Called after every edge so the power rule can write the idle-motion value it wants.
        self.after_edge: Callable[[], object] | None = None
        self._last_debug_log = float("-inf")
        self._last_info_log = float("-inf")
        self._traceback_at: dict[str, float] = {}
        self._next_reason = "reconnect"

    @property
    def owner_volume(self) -> int:
        return self._levels.volume if self._levels is not None else self._owner_volume

    @owner_volume.setter
    def owner_volume(self, value: int) -> None:
        if self._levels is not None:
            self._levels.set_volume(value)
        else:
            self._owner_volume = value

    @property
    def owner_brightness(self) -> int:
        return self._levels.brightness if self._levels is not None else self._owner_brightness

    @owner_brightness.setter
    def owner_brightness(self, value: int) -> None:
        if self._levels is not None:
            self._levels.set_brightness(value)
        else:
            self._owner_brightness = value

    def set_owner_volume_from_voice(self, level: int) -> None:
        with self._lock:
            if self.night:
                self.night_volume_override = max(0, min(100, int(level)))
                self._sync_volume()
            else:
                self.owner_volume = level
                self._sync_volume()

    def effective_brightness(self) -> int:
        """The level the screen is meant to show now (the night level at night)."""
        return self.effective_brightness_for(self.night)

    def effective_brightness_for(self, night: bool) -> int:
        if night:
            return self.night_brightness_override or NIGHT_BRIGHTNESS
        return self.owner_brightness

    def set_brightness_from_voice(self, level: int) -> None:
        """A spoken brightness: by day the stored owner level, at night only the night level."""
        level = max(0, min(100, int(level)))
        with self._lock:
            if self.night:
                self.night_brightness_override = level
            else:
                self.owner_brightness = level
            self._call(self._device.set_brightness, level)

    def set_levels_from_unit(self, volume: int | None, brightness: int | None) -> None:
        """The person moved the unit's own sliders: same rules as a spoken change.

        The unit already applied the levels; this only records them (day: the owner levels,
        night: the temporary night levels) so the next edge or reconnect restores them."""
        with self._lock:
            if volume is not None:
                if self.night:
                    self.night_volume_override = volume
                else:
                    self.owner_volume = volume
                self.applied_volume = volume
            if brightness is not None:
                if self.night:
                    self.night_brightness_override = brightness
                else:
                    self.owner_brightness = brightness

    def apply_levels(self, volume: object, brightness: object) -> None:
        """The hub's robot.volume and robot.brightness: the robot's default owner levels.

        Stored as the owner levels when they are new; applied now by day. At night the night
        level (and a spoken night override) stays, and the day level shows at the next day edge."""
        if self._levels is None:
            return
        vol = volume if isinstance(volume, int) and not isinstance(volume, bool) else None
        bri = (
            brightness if isinstance(brightness, int) and not isinstance(brightness, bool) else None
        )
        with self._lock:
            vol_new, bri_new = self._levels.note_hub_defaults(
                None if vol is None else max(0, min(100, vol)),
                None if bri is None else max(0, min(100, bri)),
            )
            if vol_new:
                self._sync_volume()
            if bri_new and not self.night:
                self._call(self._device.set_brightness, self.owner_brightness)

    def on_connect(self) -> None:
        """Force a full state write on the next poll after a unit reconnects."""
        with self._lock:
            self._synced = False
            self._next_reason = "reconnect"

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
        self.apply_levels(values.get("robot.volume"), values.get("robot.brightness"))
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
            if self._connected is not None and not self._connected():
                return self.night  # no unit to talk to: on_connect will sync it when it joins
            if not self._policy.enabled:
                self._reconcile(False)
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
            if self._clock() - self._last_debug_log >= 60.0:
                logger.debug("StackChan light reading: lux=%s camera_luma=%s", lux, luma)
                self._last_debug_log = self._clock()
            if self._clock() - self._last_info_log >= 600.0:
                # Ten-minute record of the light sensor, to judge its readings against the room.
                logger.info("StackChan light sensor: lux=%s, night=%s", lux, self.night)
                self._last_info_log = self._clock()
            if wanted != self.night:
                if quiet:
                    reason = "quiet hours"
                elif lux is not None and wanted:
                    reason = f"dark {lux:.1f} lux"
                elif lux is not None:
                    reason = f"light {lux:.1f} lux"
                elif luma is not None and wanted:
                    reason = f"dark {luma:.1f} lux"
                elif luma is not None:
                    reason = f"light {luma:.1f} lux"
                else:
                    reason = "no light reading"
                self._next_reason = reason
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
        changed = wanted != self.night
        reconnect_sync = not self._synced
        if changed or reconnect_sync:
            if not self._edge(wanted):
                return  # the face call failed; the next poll retries
            if changed or reconnect_sync:
                reason = self._next_reason if changed else "reconnect"
                logger.info("StackChan night %s (reason: %s)", "on" if wanted else "off", reason)
            self.night = wanted
            self._synced = True
            if changed and not wanted:
                self.night_volume_override = None
                self.night_brightness_override = None
        self._sync_volume(force=reconnect_sync)

    def _edge(self, night: bool) -> bool:
        d = self._device
        if not self._call(d.set_face_background, self.color, night):
            return False
        self._call(d.set_brightness, self.effective_brightness_for(night))
        if self._leds is not None:
            self._call(self._leds, not night)
        # Night turns the wandering off. Day never turns it back on here: whether the head may
        # wander is the power rule's decision (idle level, charging, unknown power), and a night
        # edge or a reconnect that enabled it put the unit wandering again (2026-10-21).
        if night:
            self._call(d.set_idle_motion, False)
        if self.after_edge is not None:
            try:
                self.after_edge()
            except Exception:
                logger.warning("night after-edge hook failed", exc_info=True)
        return True

    def _target_volume(self, night: bool) -> int:
        if not night:
            return self.owner_volume
        if self.night_volume_override is not None:
            return self.night_volume_override
        return max(0, min(100, round(self.owner_volume * NIGHT_VOLUME_SHARE)))

    def _sync_volume(self, *, force: bool = False) -> None:
        if self._alarm_active():
            return
        target = self._target_volume(self.night)
        if force or target != self.applied_volume:
            self._call(self.write_volume, target)

    def _call(self, fn: Callable[..., object], *args: object) -> bool:
        try:
            fn(*args)
            return True
        except Exception:
            name = getattr(fn, "__name__", type(fn).__name__)
            now = self._clock()
            previous = self._traceback_at.get(name, float("-inf"))
            if now - previous >= 300.0:
                self._traceback_at[name] = now
                logger.warning("night call failed: %s", name, exc_info=True)
            else:
                logger.warning("night call failed: %s", name)
            return False
