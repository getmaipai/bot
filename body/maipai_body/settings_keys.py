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
