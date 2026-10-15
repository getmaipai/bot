"""Reader for the robot API vocabulary owned by the shared spec."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from maipai_body.spec_pin import SPEC_CHECKOUT


@dataclass(frozen=True)
class PartContract:
    id: str
    capabilities: tuple[str, ...]
    capability_mode: str
    verbs: frozenset[str]
    state: frozenset[str]


@dataclass(frozen=True)
class RobotApi:
    """Part and verb names loaded from the selected commons spec source."""

    whole_robot_verbs: frozenset[str]
    parts: dict[str, PartContract]
    not_supported_fields: tuple[str, ...]

    @classmethod
    def from_spec_dir(cls, spec_dir: Path) -> RobotApi:
        """Load and validate ``vocab/robot-api.json`` from a pinned spec directory."""
        path = spec_dir / "vocab" / "robot-api.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"cannot read the shared robot API vocabulary at {path}; "
                "set MAIPAI_SPEC_DIR to the pinned spec directory"
            ) from exc

        parts: dict[str, PartContract] = {}
        for item in raw.get("parts", []):
            part_id = item["id"]
            if part_id in parts:
                raise ValueError(f"robot API vocabulary repeats part {part_id!r}: {path}")
            parts[part_id] = PartContract(
                id=part_id,
                capabilities=tuple(item["capabilities"]),
                capability_mode=item.get("capability_mode", "all"),
                verbs=frozenset(item["verbs"]),
                state=frozenset(item.get("state", [])),
            )
        # Bot-local additions are kept here until commons publishes the next
        # robot-api vocabulary revision.
        additions = {
            "audio": {"speaker.speak", "listen_window"},
            "alerts": {"show"},
            "reminders": {"create_reminder", "get_reminders", "stop_reminder"},
        }
        for part_id, verbs in additions.items():
            if part_id in parts:
                part = parts[part_id]
                parts[part_id] = PartContract(
                    id=part.id,
                    capabilities=part.capabilities,
                    capability_mode=part.capability_mode,
                    verbs=part.verbs | verbs,
                    state=part.state,
                )
            else:
                parts[part_id] = PartContract(
                    id=part_id,
                    capabilities=("speaker",) if part_id == "alerts" else ("speaker",),
                    capability_mode="any",
                    verbs=frozenset(verbs),
                    state=frozenset(),
                )
        error = next(
            (item for item in raw.get("errors", []) if item.get("id") == "NotSupported"),
            None,
        )
        if error is None:
            raise ValueError(f"robot API vocabulary has no NotSupported shape: {path}")
        fields = tuple(error["shape"]["required"])
        if set(fields) != set(error["shape"]["properties"]):
            raise ValueError(f"NotSupported fields do not match its shape: {path}")
        return cls(
            whole_robot_verbs=frozenset(raw.get("whole_robot_verbs", [])),
            parts=parts,
            not_supported_fields=fields,
        )

    def part(self, part_id: str) -> PartContract:
        try:
            return self.parts[part_id]
        except KeyError as exc:
            raise AttributeError(f"unknown robot part {part_id!r}") from exc


def default_spec_dir() -> Path:
    """Resolve the explicit test/runtime pin, with the checkout's pin as fallback."""
    import os

    configured = os.environ.get("MAIPAI_SPEC_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[4] / SPEC_CHECKOUT


def load_robot_api(spec_dir: Path | None = None) -> RobotApi:
    return RobotApi.from_spec_dir(spec_dir or default_spec_dir())
