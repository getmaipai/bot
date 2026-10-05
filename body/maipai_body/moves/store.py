"""Where taught moves live: one JSON file per name, on this device only.

A name is a plain slug, so it can never be a path, and it may not be a
name in the pinned library (a taught move never shadows Pollen's). A move
is checked as a well-formed move before anything is written, and the
write is a rename, so a half-written file never exists.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from pathlib import Path
from typing import Any

from .recorded_move import RecordedMove

_NAME = re.compile(r"[a-z0-9][a-z0-9_]{0,39}")


class BadMoveName(ValueError):
    """The name cannot be used for a taught move."""


class MoveStore:
    def __init__(self, directory: Path, reserved: Collection[str] = ()) -> None:
        self._dir = directory
        self._reserved = set(reserved)

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.json"

    def check_name(self, name: str, *, replace: bool = False) -> None:
        if not _NAME.fullmatch(name):
            raise BadMoveName(f"{name!r}: use 1 to 40 lowercase letters, digits or underscores")
        if name in self._reserved:
            raise BadMoveName(f"{name}: that is a name in the moves library")
        if self._path(name).exists() and not replace:
            raise BadMoveName(f"{name}: a move with that name exists; replace it explicitly")

    def save(self, name: str, data: dict[str, Any], *, replace: bool = False) -> None:
        self.check_name(name, replace=replace)
        RecordedMove.from_json(name, data)
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._dir / f".{name}.json.tmp"
        tmp.write_text(json.dumps(data))
        tmp.replace(self._path(name))

    def names(self) -> list[str]:
        if not self._dir.exists():
            return []
        return sorted(p.stem for p in self._dir.glob("*.json") if _NAME.fullmatch(p.stem))

    def load(self, name: str) -> RecordedMove:
        if not _NAME.fullmatch(name):
            raise BadMoveName(f"{name!r}: not a taught move name")
        return RecordedMove.from_json(name, json.loads(self._path(name).read_text()))

    def delete(self, name: str) -> None:
        if not _NAME.fullmatch(name):
            raise BadMoveName(f"{name!r}: not a taught move name")
        self._path(name).unlink()
