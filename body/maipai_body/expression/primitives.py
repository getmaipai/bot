"""The primitive vocabulary, declared once (``dev.md`` section 5).

One name per primitive; every renderer and every suppression check reads
this list, never a second copy of the names.
"""

from __future__ import annotations

PRIMITIVE_NAMES: tuple[str, ...] = (
    "listen",
    "glance",
    "tilt",
    "nod",
    "perk",
    "attend",
    "settle",
    "breathe",
    "track",
    "speak",
    "stop",
)

# "muted" is a state, not a cue-driven primitive (dev.md section 5's own
# distinction); it is rendered directly by the mute contract, never by
# map_cue_to_primitive.
MUTED_STATE = "muted"

# MOVE-CARRY-01c: the held look, antennas only. Also a state, never a cue.
HELD_STATE = "held"
