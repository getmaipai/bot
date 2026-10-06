"""EYES-02: the one look table, and the only site of a colour or a level.

Nothing else in ``indicator/`` names a palette member or a brightness
number (a grep test holds that line). The palette has no red; the eyes
never show an alarm in red, and the alarm blinks no faster than
``ALARM_PERIOD_S``.

The live cue (green: the voice is being sent to the hub) and the camera
cue outrank everything, ignore the day, night and child levels, and never
fall below their floors. ``robot.indicator.enabled`` does not reach them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from maipai_body.hal.seam import Look, Palette
from maipai_body.presence.carry_reaction import PresenceEntry
from maipai_body.presence.funnel import FunnelState

if TYPE_CHECKING:
    from maipai_body.indicator.settings import IndicatorSettings

# The least brightness the two capture cues ever show.
LIVE_FLOOR = 0.5
CAMERA_FLOOR = 0.5
# A capture cue is shown at least this long, however briefly the capture lasted.
CUE_HOLD_S = 0.5
# One full blink of the alarm (bright then dim). Never faster than 1 Hz.
ALARM_PERIOD_S = 1.0

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
    ALARM = "alarm"
    ALARM_DIM = "alarm_dim"
    HELD = "held"
    MUTED = "muted"
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    SLEEP = "sleep"


# row: (colour, weight). The weight is the share of the day or night level the
# row uses; the cues and the alarm are not scaled by it (see ``resolve``).
LOOKS: dict[LookKey, tuple[Palette, float]] = {
    LookKey.LIVE: (Palette.GREEN, 1.0),
    LookKey.CAMERA: (Palette.CYAN, 1.0),
    LookKey.ALARM: (Palette.AMBER, 1.0),
    LookKey.ALARM_DIM: (Palette.AMBER, 0.15),
    LookKey.HELD: (Palette.MAGENTA, 0.5),
    LookKey.MUTED: (Palette.AMBER, 0.4),
    LookKey.IDLE: (Palette.WHITE, 0.35),
    LookKey.LISTENING: (Palette.BLUE, 1.0),
    LookKey.THINKING: (Palette.MAGENTA, 0.8),
    LookKey.SPEAKING: (Palette.WHITE, 1.0),
    LookKey.SLEEP: (Palette.BLUE, 0.3),
}

_FUNNEL_ROWS = {
    FunnelState.IDLE: LookKey.IDLE,
    FunnelState.LISTENING: LookKey.LISTENING,
    FunnelState.THINKING: LookKey.THINKING,
    FunnelState.SPEAKING: LookKey.SPEAKING,
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
    alarm: bool = False
    alarm_on: bool = False
    held: bool = False
    muted: bool = False


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


def level(request: LookRequest) -> float:
    settings = request.settings
    if not is_night(request.minute, settings.night_from, settings.night_to):
        return settings.brightness
    night = settings.night_brightness
    return night * LOWEST_NIGHT_FACTOR if _lowest_night(request.presence) else night


def _row(key: LookKey, brightness: float) -> Look | None:
    colour, _ = LOOKS[key]
    if brightness <= 0.0:
        return None
    return Look(colour=colour, brightness=min(1.0, brightness))


def _cue(key: LookKey, floor: float, settings: IndicatorSettings) -> Look:
    colour, weight = LOOKS[key]
    return Look(colour=colour, brightness=min(1.0, max(floor, weight * settings.brightness)))


def resolve(request: LookRequest) -> Look | None:
    """The look to show, or ``None`` for dark. Priority, highest first: live,
    camera, alarm, then (when enabled) held, muted, and the funnel state."""
    settings = request.settings
    if request.live:
        return _cue(LookKey.LIVE, LIVE_FLOOR, settings)
    if request.camera:
        return _cue(LookKey.CAMERA, CAMERA_FLOOR, settings)
    if request.alarm and settings.alarm:
        key = LookKey.ALARM if request.alarm_on else LookKey.ALARM_DIM
        return Look(colour=LOOKS[key][0], brightness=LOOKS[key][1])
    if not settings.enabled:
        return None
    base = level(request)
    if request.held:
        return _row(LookKey.HELD, LOOKS[LookKey.HELD][1] * base)
    if request.muted:
        return _row(LookKey.MUTED, LOOKS[LookKey.MUTED][1] * base)
    if request.funnel is FunnelState.IDLE and is_night(
        request.minute, settings.night_from, settings.night_to
    ):
        if settings.sleep_eyes == "off":
            return None
        return _row(LookKey.SLEEP, LOOKS[LookKey.SLEEP][1] * base)
    key = _FUNNEL_ROWS[request.funnel]
    return _row(key, LOOKS[key][1] * base)
