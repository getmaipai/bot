"""Small value types shared by the robot object and its body adapters."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RobotStateFrame(BaseModel):
    """One monotonic, sequence-numbered snapshot of the parts that reported."""

    t_received_ns: int = Field(ge=0)
    seq: int = Field(ge=0)
    parts: dict[str, Any]
