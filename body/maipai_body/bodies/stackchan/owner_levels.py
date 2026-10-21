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

    def load(self) -> None:
        self.volume, self.brightness, self.volume_stored = 70, 100, False
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
                json.dump({"volume": self.volume, "brightness": self.brightness}, temp)
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
