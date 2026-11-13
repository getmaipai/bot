"""EYES-02: the one look table, and the only site of a colour or a level.

Nothing else in ``indicator/`` names a palette member or a brightness
number (a grep test holds that line). The palette has no red.

The table is the ring standard approved by the owner on 2026-11-13
(``docs/dev/led-standard-2026-10-20.md``, "The ring table"): the ring is
dark unless it tells a person something they need right now. Five colours,
one meaning each: green = your voice is leaving the robot, pink = a picture
is being taken, cyan = I need a person, amber = look at the screen, blue =
your turn. A test parses that table and fails when a ``LookKey`` or a look
differs from it.

The live cue (green) and the camera cue (pink) outrank everything, ignore
the day, night and child levels, and never fall below their floors.
``robot.indicator.enabled`` does not reach them. Asleep, the ring is dark
except for those two. At night (quiet hours or a dark room) the amber
attention pulse stays dark too.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from maipai_body.hal.seam import Look, LookStyle, Palette
from maipai_body.presence.carry_reaction import PresenceEntry
from maipai_body.presence.funnel import FunnelState

if TYPE_CHECKING:
    from maipai_body.indicator.settings import IndicatorSettings

# The least brightness the two capture cues ever show.
LIVE_FLOOR = 0.5
CAMERA_FLOOR = 0.5
# A capture cue is shown at least this long, however briefly the capture lasted.
CUE_HOLD_S = 0.5
# The attention row shows only after its cause has lasted this long (a blip is not news).
ATTENTION_AFTER_S = 10.0

# The levels the settings keys scale and declare.
DAY_LEVEL_DEFAULT = 0.6
DAY_LEVEL_RANGE = (0.2, 1.0)
NIGHT_LEVEL_DEFAULT = 0.15
NIGHT_LEVEL_RANGE = (0.0, 0.5)
# At night the level is multiplied by this when a child, a teen, an unknown
# person or no presence information is in the room. A rule on the presence
# list, not a settings key.
LOWEST_NIGHT_FACTOR = 0.4


class LookKey(StrEnum):
    LIVE = "live"
    CAMERA = "camera"
    PAIRING = "pairing"
    ATTENTION = "attention"
    LISTENING = "listening"
    # The one decorative show. The little dance (dance.py) paints its own light show; the light
    # service raises ``dancing`` and stops painting while it runs.
    DANCE = "dance"
    IDLE = "idle"


# row: (colour, weight, style). For the share rows (listening) the weight is the share of the
# day or night level; the cues keep their floors; pairing and attention are fixed brightnesses.
LOOKS: dict[LookKey, tuple[Palette, float, LookStyle]] = {
    LookKey.LIVE: (Palette.GREEN, 1.0, LookStyle.STEADY),
    LookKey.CAMERA: (Palette.PINK, 1.0, LookStyle.FLASH),
    LookKey.PAIRING: (Palette.CYAN, 0.6, LookStyle.PULSE),
    # ONE amber, "look at the screen": offline, a fault and a low battery share it.
    LookKey.ATTENTION: (Palette.AMBER, 0.3, LookStyle.PULSE),
    LookKey.LISTENING: (Palette.BLUE, 1.0, LookStyle.STEADY),
    LookKey.DANCE: (Palette.MAGENTA, 0.5, LookStyle.STEADY),
    # Dark: idle, thinking, speaking, charging, boot, ready, night, sleep. Weight 0 gives None.
    LookKey.IDLE: (Palette.WHITE, 0.0, LookStyle.STEADY),
}
# Rows shown at their own brightness, not scaled by the day or night level.
FIXED_ROWS = frozenset({LookKey.PAIRING, LookKey.ATTENTION})

# The period each style runs at. UNMEASURED design defaults; a key named in
# ``STYLE_PERIOD_S`` uses that value instead of its style's.
PERIOD_S: dict[LookStyle, float] = {
    LookStyle.BREATHE: 3.0,
    LookStyle.PULSE: 2.0,
    LookStyle.FLASH: 0.5,
    LookStyle.BLINK: 1.0,
    LookStyle.DOUBLE: 10.0,
    LookStyle.STEADY: 0.0,
}
# Per-key periods that differ from their style's default.
STYLE_PERIOD_S: dict[LookKey, float] = {
    LookKey.PAIRING: 2.0,
    LookKey.ATTENTION: 10.0,
}


@dataclass(frozen=True)
class LookRequest:
    """Everything ``resolve`` decides from. ``minute`` is the local minute of the day."""

    funnel: FunnelState
    minute: int
    settings: IndicatorSettings
    presence: Sequence[PresenceEntry] | None
    live: bool = False
    camera: bool = False
    fault: bool = False
    offline: bool = False
    pairing: bool = False
    battery_low: bool = False
    dancing: bool = False
    asleep: bool = False  # the rest renderer's asleep stage: dark but for the two capture cues
    dark_room: bool = False  # the night controller's sensor night, the same as quiet hours


def is_night(minute: int, start: int, end: int) -> bool:
    """True inside the night window, which may wrap midnight. Equal ends: never."""
    if start == end:
        return False
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def _lowest_night(presence: Sequence[PresenceEntry] | None) -> bool:
    """None is no information, which counts as unknown; an empty list is nobody."""
    if presence is None:
        return True
    return any(entry.kind != "adult" for entry in presence)


def is_night_now(request: LookRequest) -> bool:
    settings = request.settings
    return request.dark_room or is_night(request.minute, settings.night_from, settings.night_to)


def level(request: LookRequest) -> float:
    if not is_night_now(request):
        return request.settings.brightness
    night = request.settings.night_brightness
    return night * LOWEST_NIGHT_FACTOR if _lowest_night(request.presence) else night


def period_s(key: LookKey) -> float:
    """The period for ``key``: a per-key override first, else its style's period."""
    override = STYLE_PERIOD_S.get(key)
    if override is not None:
        return override
    return PERIOD_S[LOOKS[key][2]]


def _row(key: LookKey, brightness: float) -> Look | None:
    colour, _, style = LOOKS[key]
    if brightness <= 0.0:
        return None
    return Look(colour=colour, brightness=min(1.0, brightness), style=style, period_s=period_s(key))


def _cue(key: LookKey, floor: float, settings: IndicatorSettings) -> Look:
    colour, weight, style = LOOKS[key]
    return Look(
        colour=colour,
        brightness=min(1.0, max(floor, weight * settings.brightness)),
        style=style,
        period_s=period_s(key),
    )


def resolve_key(request: LookRequest) -> LookKey | None:
    """The winning table key, or ``None`` for dark. The single place the
    priority order lives (live, camera, pairing, attention, listening, dance);
    ``resolve`` builds the look from it so the two never disagree."""
    if request.live:
        return LookKey.LIVE
    if request.camera:
        return LookKey.CAMERA
    if not request.settings.enabled or request.asleep:
        return None
    night = is_night_now(request)
    if request.pairing:
        return LookKey.PAIRING
    if (request.offline or request.fault or request.battery_low) and not night:
        return LookKey.ATTENTION
    if request.funnel is FunnelState.LISTENING:
        return LookKey.LISTENING
    # Thinking and speaking are dark: the face and the voice carry them.
    if request.dancing and request.funnel is FunnelState.IDLE and not night:
        return LookKey.DANCE
    return None


def resolve(request: LookRequest) -> Look | None:
    """The look to show, or ``None`` for dark. Built from ``resolve_key``."""
    settings = request.settings
    key = resolve_key(request)
    if key is None:
        return None
    if key is LookKey.LIVE:
        return _cue(LookKey.LIVE, LIVE_FLOOR, settings)
    if key is LookKey.CAMERA:
        return _cue(LookKey.CAMERA, CAMERA_FLOOR, settings)
    if key in FIXED_ROWS:
        return _row(key, LOOKS[key][1])
    return _row(key, LOOKS[key][1] * level(request))
