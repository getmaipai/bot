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
    OFFER = "offer"
    ERROR = "error"
    CONNECTING = "connecting"
    OFFLINE = "offline"
    PAIRING = "pairing"
    CHARGING = "charging"
    BATTERY_LOW = "battery_low"
    UPDATING = "updating"
    DANCING = "dancing"


# row: (colour, weight, style). The weight is the share of the day or night level
# the row uses; the cues and the alarm are not scaled by it (see ``resolve``).
LOOKS: dict[LookKey, tuple[Palette, float, LookStyle]] = {
    LookKey.LIVE: (Palette.GREEN, 1.0, LookStyle.STEADY),
    LookKey.CAMERA: (Palette.PINK, 1.0, LookStyle.FLASH),
    LookKey.ALARM: (Palette.AMBER, 1.0, LookStyle.STEADY),
    LookKey.ALARM_DIM: (Palette.AMBER, 0.15, LookStyle.STEADY),
    LookKey.HELD: (Palette.MAGENTA, 0.5, LookStyle.STEADY),
    LookKey.MUTED: (Palette.AMBER, 0.4, LookStyle.STEADY),
    LookKey.IDLE: (Palette.WHITE, 0.35, LookStyle.STEADY),
    LookKey.LISTENING: (Palette.BLUE, 1.0, LookStyle.STEADY),
    LookKey.THINKING: (Palette.MAGENTA, 0.8, LookStyle.BREATHE),
    LookKey.SPEAKING: (Palette.WHITE, 1.0, LookStyle.STEADY),
    LookKey.SLEEP: (Palette.BLUE, 0.3, LookStyle.STEADY),
    # OFFER-01: the robot has asked and listens locally for a yes or no. Not green: nothing
    # is leaving for the hub. THERMAL-01/MOTOR-RECOVER-01: a real fault, steady amber (no red).
    LookKey.OFFER: (Palette.BLUE, 0.6, LookStyle.STEADY),
    LookKey.ERROR: (Palette.AMBER, 0.7, LookStyle.STEADY),
    LookKey.CONNECTING: (Palette.BLUE, 0.5, LookStyle.PULSE),
    LookKey.OFFLINE: (Palette.AMBER, 0.3, LookStyle.DOUBLE),
    LookKey.PAIRING: (Palette.CYAN, 0.6, LookStyle.PULSE),
    LookKey.CHARGING: (Palette.GREEN, 0.3, LookStyle.BREATHE),
    LookKey.BATTERY_LOW: (Palette.AMBER, 0.3, LookStyle.PULSE),
    LookKey.UPDATING: (Palette.WHITE, 0.5, LookStyle.PULSE),
    LookKey.DANCING: (Palette.WHITE, 0.35, LookStyle.STEADY),
}

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
    LookKey.CHARGING: 4.0,
    LookKey.CONNECTING: 2.0,
    LookKey.UPDATING: 1.0,
    LookKey.PAIRING: 2.0,
    LookKey.OFFLINE: 10.0,
    LookKey.BATTERY_LOW: 20.0,
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
    offer: bool = False
    fault: bool = False
    connecting: bool = False
    offline: bool = False
    pairing: bool = False
    charging: bool = False
    battery_low: bool = False
    updating: bool = False
    dancing: bool = False


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
    priority order lives; ``resolve`` builds the look from it so the two
    never disagree."""
    settings = request.settings
    if request.live:
        return LookKey.LIVE
    if request.camera:
        return LookKey.CAMERA
    if request.alarm and settings.alarm:
        return LookKey.ALARM if request.alarm_on else LookKey.ALARM_DIM
    if not settings.enabled:
        return None
    if request.fault:
        return LookKey.ERROR
    if request.held:
        return LookKey.HELD
    if request.muted:
        return LookKey.MUTED
    if request.updating:
        return LookKey.UPDATING
    if request.pairing:
        return LookKey.PAIRING
    if request.connecting:
        return LookKey.CONNECTING
    if request.offline:
        return LookKey.OFFLINE
    if request.battery_low:
        return LookKey.BATTERY_LOW
    if request.offer and request.funnel is FunnelState.IDLE:
        return LookKey.OFFER
    if request.charging and request.funnel is FunnelState.IDLE:
        return LookKey.CHARGING
    if request.funnel is FunnelState.IDLE and is_night(
        request.minute, settings.night_from, settings.night_to
    ):
        if settings.sleep_eyes == "off":
            return None
        return LookKey.SLEEP
    if request.dancing and request.funnel is FunnelState.IDLE:
        return LookKey.DANCING
    return _FUNNEL_ROWS[request.funnel]


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
    if key in (LookKey.ALARM, LookKey.ALARM_DIM):
        colour, weight, style = LOOKS[key]
        return Look(colour=colour, brightness=weight, style=style)
    return _row(key, LOOKS[key][1] * level(request))
