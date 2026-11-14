"""Settings keys shared by body settings consumers."""

FACE_COLOR_KEY = "robot.face.color"
NIGHT_MODE_KEY = "robot.night.mode"
QUIET_FROM_KEY = "household.quiet_hours.from"
QUIET_TO_KEY = "household.quiet_hours.to"
POWER_WARN_AT_KEY = "robot.power.warn_at"
DEFAULT_POWER_WARN_AT = 20
FACE_PALETTES = frozenset({"mint", "sky", "peach", "lavender", "lemon", "rose", "cloud"})


def face_color(values: object) -> str:
    """Read the named face palette with its safe registry default."""
    if not isinstance(values, dict):
        return "mint"
    value = values.get(FACE_COLOR_KEY, "mint")
    return value if isinstance(value, str) and value in FACE_PALETTES else "mint"


def night_mode(values: object) -> bool:
    """Read night mode; malformed or absent values use its on default."""
    if not isinstance(values, dict):
        return True
    value = values.get(NIGHT_MODE_KEY, True)
    return value if isinstance(value, bool) else True


# On-unit timers and alarms (StackChan firmware patches 090 to 094): off stops new ones being set;
# what the unit already holds still rings. Home's registry default is on.
TIMERS_ENABLED_KEY = "robot.timers.enabled"
# Hub announcements ("say this"): off refuses them; muted and quiet are read only if Home
# sends them.
ANNOUNCE_ENABLED_KEY = "robot.announce.enabled"
MUTED_KEY = "robot.muted"
QUIET_KEY = "robot.quiet"
# "Say that again", "what did you say", "what did I miss": answered on the robot from the last few
# replies and a small log of what it could not tell the person; off sends them to the hub like any
# other question (and keeps nothing). Home's registry default is on.
REPEAT_ENABLED_KEY = "robot.repeat.enabled"
# StackChan hard mute (firmware patches 105 to 108): vision off, and whether the unit's own face may
# turn listening back on. Home's registry defaults: false and true.
VISION_OFF_KEY = "robot.vision_off"
LOCAL_UNMUTE_KEY = "robot.mute.local_unmute"
# The StackChan's own sounds (firmware patches 115 to 118, bodies/stackchan/sounds.py). Both are
# device-scope registry keys honoured by the bot: event sounds on (default true) and event sounds
# also at night (default false). The safety and privacy cues (a picture, a low battery, an error)
# ignore "off" and the night rule; the hard mute (MUTED_KEY, QUIET_KEY) silences all of them.
SOUNDS_ENABLED_KEY = "robot.sounds.enabled"
SOUNDS_NIGHT_KEY = "robot.sounds.night"


# SELF-SCENE-02: the battery percent at which the robot gives its one short low-battery line
# (admin-moved; default 20). Degrade, dock and sleep stay at 15, 10 and 5, so the value is
# kept between 16 and 50.
def power_warn_at(values: object) -> int:
    """Read ``robot.power.warn_at``; malformed or absent values use the default 20."""
    if not isinstance(values, dict):
        return DEFAULT_POWER_WARN_AT
    value = values.get(POWER_WARN_AT_KEY, DEFAULT_POWER_WARN_AT)
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_POWER_WARN_AT
    return max(16, min(50, value))
