"""Settings keys shared by body settings consumers."""

FACE_COLOR_KEY = "robot.face.color"
NIGHT_MODE_KEY = "robot.night.mode"
QUIET_FROM_KEY = "household.quiet_hours.from"
QUIET_TO_KEY = "household.quiet_hours.to"
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
