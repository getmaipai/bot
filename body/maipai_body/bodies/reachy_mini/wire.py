"""Parsing shared by the live client and the fake: one daemon wire shape.

Both `client.py` (from the live WebSocket) and `fake.py` (from recorded
JSON lines) build a `StateFrame` from the same payload shape the daemon's
`FullState` model serializes (`head_pose`, `antennas_position`, `body_yaw`,
`doa`), so the parsing lives here once.
"""

from __future__ import annotations

from maipai_body.hal.seam import DoAReading, HeadPose, StateFrame


def frame_from_full_state_payload(payload: dict, monotonic_ns: int) -> StateFrame:
    head = payload.get("head_pose") or {}
    antennas = payload.get("antennas_position") or [0.0, 0.0]
    doa = payload.get("doa")
    return StateFrame(
        monotonic_ns=monotonic_ns,
        head_pose=HeadPose(
            x=head.get("x", 0.0),
            y=head.get("y", 0.0),
            z=head.get("z", 0.0),
            roll=head.get("roll", 0.0),
            pitch=head.get("pitch", 0.0),
            yaw=head.get("yaw", 0.0),
        ),
        antennas=(antennas[0], antennas[1]),
        body_yaw=payload.get("body_yaw", 0.0),
        doa=DoAReading(**doa) if doa else None,
    )
