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
    # S-EXPR-04 (design v2 section 4.2): discrete cues that end at neutral.
    "thinking",
    "offer",
    "shake",
)

# "muted" is a state, not a cue-driven primitive (dev.md section 5's own
# distinction); it is rendered directly by the mute contract, never by
# map_cue_to_primitive.
MUTED_STATE = "muted"

# MOVE-CARRY-01c: the held look, antennas only. Also a state, never a cue.
HELD_STATE = "held"

# S-EXPR-04: sleep is a state like muted, entered by SLEEP-AUTO-01 or quiet
# hours. Head lowered, antennas mid-low, wake word live; it must differ from
# MUTED_STATE on the antenna axis (asserted in tests/test_sleep_state.py).
SLEEP_STATE = "sleep"

# ALARM-PLAY-01: the safety alarm pose, head up and antennas high, held still.
# A state like sleep, never a cue; the hub's alarm command enters and leaves it.
ALARM_STATE = "alarm"

# Primitives that return to neutral on their own and so release the
# expression layer when done, letting gaze and idle resume.
RELEASING_PRIMITIVES: frozenset[str] = frozenset({"thinking", "offer", "shake"})
