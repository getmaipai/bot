"""Configurable fake body that records commands and replays state frames."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maipai_body.hal.seam import BodyProfile
from maipai_body.robot import Robot, RobotApi, RobotStateFrame, load_robot_api

from .profile import FAKE_PROFILE

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_FRAMES = FIXTURES_DIR / "robot-state.jsonl"


@dataclass(frozen=True)
class FakeCommand:
    part: str
    verb: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class _FakePart:
    def __init__(self, part: str, commands: list[FakeCommand], state: dict[str, Any]) -> None:
        self.part = part
        self.commands = commands
        self.state = state

    def command(self, verb: str, *args: Any, **kwargs: Any) -> Any:
        self.commands.append(FakeCommand(self.part, verb, args, dict(kwargs)))
        if self.part == "connection" and verb in {"connect", "disconnect"}:
            value = "up" if verb == "connect" else "down"
            self.state.setdefault("connection", {})["state"] = value
            return value
        if self.part == "power" and verb in {"wake", "sleep", "power_on", "shutdown"}:
            value = {"wake": "awake", "power_on": "on", "sleep": "sleeping", "shutdown": "off"}[
                verb
            ]
            self.state.setdefault("power", {})["state"] = value
            return value
        if self.part == "estop" and verb in {"engage", "release"}:
            self.state.setdefault("estop", {})["engaged"] = verb == "engage"
            return self.state["estop"]["engaged"]
        return None

    def read(self, field: str) -> Any:
        values = self.state.get(self.part, {})
        if field in values:
            return values[field]
        raise AttributeError(field)


class _FakeState:
    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self.frames = frames
        self._last_stamp = 0

    def command(self, verb: str, *_: Any, **__: Any) -> Iterator[RobotStateFrame]:
        if verb != "stream":
            raise AttributeError(verb)
        return self.stream()

    def stream(self) -> Iterator[RobotStateFrame]:
        for row in self.frames:
            stamp = max(time.monotonic_ns(), self._last_stamp + 1)
            self._last_stamp = stamp
            yield RobotStateFrame(t_received_ns=stamp, seq=row["seq"], parts=row["parts"])


class FakeBody:
    """Create a robot with any capability subset and a recorded state timeline."""

    def __init__(
        self,
        capabilities: Iterable[str] | None = None,
        *,
        spec_dir: Path | None = None,
        frame_path: Path = DEFAULT_FRAMES,
    ) -> None:
        self.api: RobotApi = load_robot_api(spec_dir)
        selected = (
            list(capabilities) if capabilities is not None else list(FAKE_PROFILE.capabilities)
        )
        caps_path = (spec_dir or self._spec_dir()) / "vocab" / "capabilities.json"
        known_caps = set(json.loads(caps_path.read_text(encoding="utf-8"))["capabilities"])
        unknown = sorted(set(selected) - known_caps)
        if unknown:
            raise ValueError(
                f"fake body profile contains unknown capabilities {unknown}; "
                f"use ids from {caps_path}"
            )
        self.profile: BodyProfile = FAKE_PROFILE.model_copy(
            update={"capabilities": selected, "id": "fake_replay"}
        )
        self.commands: list[FakeCommand] = []
        rows = [
            json.loads(line)
            for line in frame_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self._validate_frames(rows)
        state: dict[str, Any] = {
            "connection": {"state": "down"},
            "power": {"state": "off"},
            "estop": {"engaged": False},
        }
        if rows:
            state.update(rows[-1]["parts"])
        drivers: dict[str, object] = {}
        for part_id, contract in self.api.parts.items():
            missing = set(contract.capabilities) - set(selected)
            present = (
                not missing
                if contract.capability_mode == "all"
                else len(missing) < len(contract.capabilities)
            )
            if not present:
                continue
            if part_id == "state":
                drivers[part_id] = _FakeState(rows)
            else:
                drivers[part_id] = _FakePart(part_id, self.commands, state)
        self.robot = Robot(self.profile, drivers, self.api)

    @staticmethod
    def _spec_dir() -> Path:
        from maipai_body.robot.api import default_spec_dir

        return default_spec_dir()

    @staticmethod
    def _validate_frames(rows: list[dict[str, Any]]) -> None:
        sequence = [row.get("seq") for row in rows]
        if sequence != sorted(sequence) or len(sequence) != len(set(sequence)):
            raise ValueError("fake state frames must have unique, increasing seq values")
        if any(not isinstance(row.get("parts"), dict) for row in rows):
            raise ValueError("each fake state frame needs a parts object")


__all__ = ["FakeBody", "FakeCommand"]
