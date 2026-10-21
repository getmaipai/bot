"""Persist the household owner's preferred StackChan speaker and screen levels."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger("maipai_body.bodies.stackchan.owner_levels")


class OwnerLevels:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.volume = 70
        self.brightness = 100
        self.volume_stored = False  # True once a volume was ever saved or loaded
        # The last robot.volume / robot.brightness the hub sent. A default is applied only when
        # it differs from this, so a later settings_changed that repeats it cannot undo a level
        # the person set by voice or on the unit.
        self.hub_volume: int | None = None
        self.hub_brightness: int | None = None

    def load(self) -> None:
        self.volume, self.brightness, self.volume_stored = 70, 100, False
        self.hub_volume = self.hub_brightness = None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            volume = data.get("volume")
            brightness = data.get("brightness")
            if isinstance(volume, int) and not isinstance(volume, bool):
                self.volume = max(0, min(100, volume))
                self.volume_stored = True
            if isinstance(brightness, int) and not isinstance(brightness, bool):
                self.brightness = max(0, min(100, brightness))
            for attr, key in (("hub_volume", "hub_volume"), ("hub_brightness", "hub_brightness")):
                value = data.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    setattr(self, attr, max(0, min(100, value)))
        except (OSError, ValueError, TypeError):
            return

    def save(self) -> None:
        temp_name = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as temp:
                temp_name = temp.name
                record = {"volume": self.volume, "brightness": self.brightness}
                if self.hub_volume is not None:
                    record["hub_volume"] = self.hub_volume
                if self.hub_brightness is not None:
                    record["hub_brightness"] = self.hub_brightness
                json.dump(record, temp)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp_name, self.path)
            self.volume_stored = True
        except (OSError, TypeError, ValueError) as exc:
            logger.warning(
                "Could not save owner levels at %s: %s. Check that the directory is writable.",
                self.path,
                exc,
            )
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass

    def set_volume(self, value: int) -> None:
        level = max(0, min(100, int(value)))
        if level != self.volume:
            self.volume = level
            self.save()

    def set_brightness(self, value: int) -> None:
        level = max(0, min(100, int(value)))
        if level != self.brightness:
            self.brightness = level
            self.save()

    def note_hub_defaults(self, volume: int | None, brightness: int | None) -> tuple[bool, bool]:
        """Take the hub's robot.volume / robot.brightness as the owner levels when they changed.

        Returns (volume_changed, brightness_changed). A value equal to the last one the hub sent
        is not a new default and leaves the stored level alone."""
        volume_changed = brightness_changed = False
        if volume is not None and volume != self.hub_volume:
            self.hub_volume = volume
            self.volume = volume
            volume_changed = True
        if brightness is not None and brightness != self.hub_brightness:
            self.hub_brightness = brightness
            self.brightness = brightness
            brightness_changed = True
        if volume_changed or brightness_changed:
            self.save()
        return volume_changed, brightness_changed
